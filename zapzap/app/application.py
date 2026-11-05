"""Application bootstrap and lifecycle orchestration."""

import sys
import configparser
import os

import zapzap
from PyQt6.QtCore import QCoreApplication, QTimer, Qt
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices, QFont
from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEngineScript

from zapzap.app.single_application import SingleApplication
from zapzap.app.desktop_application_dbus import DesktopApplicationDBus
from zapzap.app.main_window_controller import MainWindowController
from zapzap.features.browser.shell.browser_controller import (
    load_webview_factory,
)
from zapzap.app.startup_options import apply_startup_options, parse_startup_options
from zapzap.app.unix_signal_bridge import install_unix_signal_bridge
from zapzap.app.window_lifecycle import ClientSideWindowHost
from zapzap.core.diagnostics import crash_handler
from zapzap.assets.icons.tray_icon import TrayIcon
from zapzap.core.environment.proxy_manager import ProxyManager
from zapzap.core.config.settings_manager import SettingsManager
from zapzap.core.config.settings.appearance import AppearanceSettings
from zapzap.core.config.settings.system import SystemSettings
from zapzap.core.environment.setup_manager import SetupManager
from zapzap.core.theme.theme_manager import ThemeManager
from zapzap.core.update_checker import UpdateChecker, UpdateState
from zapzap.core.i18n.translation_manager import TranslationManager
from zapzap.features.initial_setup.controller import InitialSetupController
from zapzap.features.donation.controller import DonationController
from zapzap.features.dictionaries.system_dictionary_provisioner import (
    SystemDictionaryProvisioner,
)
from PyQt6.QtWidgets import QWidget
from zapzap.features.notifications.notification_service import (
    NotificationService,
    is_flatpak,
)
from zapzap.features.reporting.coordinator import ReportingCoordinator
from zapzap.core.reporting.capture import CrashSessionMonitor
from zapzap.core.diagnostics.webengine_probe import probe

def load_external_font_config():
    """Proje kök dizinindeki zapzap_font.conf dosyasından ayarları okur."""
    config = configparser.ConfigParser()
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ini_path = os.path.join(base_dir, "zapzap_font.conf")

    defaults = {"font_family": "Source Sans Pro", "menu_size": "11", "whatsapp_size": "12"}

    if os.path.exists(ini_path):
        config.read(ini_path)
        if "FontSettings" in config:
            return {
                "font_family": config.get("FontSettings", "font_family", fallback=defaults["font_family"]),
                "menu_size": config.getint("FontSettings", "menu_size", fallback=int(defaults["menu_size"])),
                "whatsapp_size": config.getint("FontSettings", "whatsapp_size", fallback=int(defaults["whatsapp_size"]))
            }
    return {
        "font_family": defaults["font_family"],
        "menu_size": int(defaults["menu_size"]),
        "whatsapp_size": int(defaults["whatsapp_size"])
    }

def create_main_window(webview_factory=None, update_state=None, update_checker=None):
    """Build a fresh MainWindow instance using the current runtime settings."""
    content = MainWindowController(
        webview_factory=webview_factory,
        update_state=update_state,
        update_checker=update_checker,
    )

    # =========================================================================
    # WHATSAPP SOHBET ALANI İÇİN KESİN FONT VE BOYUT TAZELEYİCİ
    # =========================================================================
    def apply_whatsapp_font():
        f_conf = load_external_font_config()
        try:
            browser_ctrl = getattr(content, "browser", None)
            if browser_ctrl:
                page = browser_ctrl.current_webview()
                if page:
                    profile = page.page().profile()
                    if profile:
                        settings = profile.settings()
                        settings.setFontFamily(settings.FontFamily.StandardFont, f_conf["font_family"])
                        settings.setFontFamily(settings.FontFamily.SansSerifFont, f_conf["font_family"])
                        settings.setFontSize(settings.FontSize.DefaultFontSize, int(f_conf["whatsapp_size"] * 1.33))

                    # Birimi px yerine pt (punto) yaparak Chromium ölçekleme hatasını ezdik
                    css_injection = f"""
                    body, body *, html, html *, p, span, div, input, textarea, [contenteditable] {{
                        font-family: '{f_conf["font_family"]}', sans-serif !important;
                        font-size: {f_conf["whatsapp_size"]}pt !important;
                    }}
                    """
                    js_code = f"""
                    (function() {{
                        var id = 'zapzap-fontsize-final-fix';
                        var style = document.getElementById(id);
                        if (!style) {{
                            style = document.createElement('style');
                            style.id = id;
                            style.type = 'text/css';
                            document.documentElement.appendChild(style);
                        }}
                        style.innerHTML = `{css_injection}`;
                    }})();
                    """
                    page.page().runJavaScript(js_code)
        except Exception:
            pass

    try:
        browser_ctrl = getattr(content, "browser", None)
        if browser_ctrl:
            browser_ctrl.pages.currentChanged.connect(lambda _: apply_whatsapp_font())

            QTimer.singleShot(1000, apply_whatsapp_font)
            QTimer.singleShot(3000, apply_whatsapp_font)
            QTimer.singleShot(6000, apply_whatsapp_font)
            QTimer.singleShot(12000, apply_whatsapp_font)
    except Exception:
        pass
    # =========================================================================

    appearance = AppearanceSettings()
    window = ClientSideWindowHost(content) if appearance.csr_enabled else content
    if DonationController.should_show():
        DonationController.showMessage(parent=window)

    return window
def main():
    args, _unknown = parse_startup_options()
    apply_startup_options(args)

    QCoreApplication.setApplicationName(zapzap.__appname__)
    QCoreApplication.setOrganizationDomain(zapzap.__domain__)

    SetupManager.apply()
    TranslationManager.apply()

    webview_factory = load_webview_factory()
    crash_handler.install()

    app = SingleApplication(
        zapzap.__appid__, sys.argv + SetupManager.get_argv())

    app.setApplicationName(zapzap.__appname__)
    app.setApplicationVersion(zapzap.__version__)
    app.setDesktopFileName(zapzap.__desktopid__)
    app.setOrganizationDomain(zapzap.__domain__)

    crash_session_monitor = CrashSessionMonitor(
        faulthandler_path=crash_handler.faulthandler_path,
    )
    crash_session_monitor.start()
    probe.configure(crash_handler.dump_dir, crash_session_monitor.session_id)
    app.setWindowIcon(TrayIcon.getIcon())
    unix_signal_bridge = install_unix_signal_bridge(app)

    SetupManager.apply_qt_scale_factor_rounding_policy()
    ProxyManager.apply()

    def handle_instance_message(result):
        if result == app.RESTART_MESSAGE:
            app.restartApplication()
            return
        app.getWindow().xdgOpenChat(result)

    app.messageReceived.connect(handle_instance_message)
    ThemeManager.start()

    update_state = UpdateState(app)
    update_checker = UpdateChecker(update_state, app)

    main_window = app.startInterface(
        lambda: create_main_window(
            webview_factory,
            update_state,
            update_checker,
        )
    )

    system_dictionary_provisioner = SystemDictionaryProvisioner(app)
    system_dictionary_provisioner.dictionary_installed.connect(
        lambda _code: app.getWindow().browser.update_spellcheck()
    )
    system_dictionary_provisioner.start()

    desktop_application_dbus = None
    if is_flatpak():
        desktop_application_dbus = DesktopApplicationDBus(app)
        desktop_application_dbus.start()

    if SettingsManager.get("website/open_page", True):
        QDesktopServices.openUrl(QUrl(zapzap.__website__))
        SettingsManager.set("website/open_page", False)

    should_show_initial_setup = InitialSetupController.should_show()

    if (
        SystemSettings().start_in_background or '--hideStart' in sys.argv
    ) and not should_show_initial_setup:
        main_window.hide()
    else:
        # =========================================================================
        # PENCEREYI SAĞ ALT KÖŞEYE OTOMATİK KONUMLANDIRMA VE ÜSTTE TUTMA
        # =========================================================================
        try:
            config = configparser.ConfigParser()
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            ini_path = os.path.join(base_dir, "zapzap_font.conf")

            auto_align = False
            w_width, w_height = 380, 600

            if os.path.exists(ini_path):
                config.read(ini_path)
                if "WindowSettings" in config:
                    auto_align = config.getboolean("WindowSettings", "auto_align_right_bottom", fallback=False)
                    w_width = config.getint("WindowSettings", "width", fallback=380)
                    w_height = config.getint("WindowSettings", "height", fallback=600)

            if auto_align:
                main_window.showNormal()
                main_window.setWindowFlags(main_window.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)

                screen = app.primaryScreen()
                if screen:
                    screen_geometry = screen.availableGeometry()
                    screen_width = screen_geometry.width()
                    screen_height = screen_geometry.height()

                    x_position = screen_width - w_width - 15
                    y_position = screen_height - w_height - 15

                    main_window.resize(w_width, w_height)
                    main_window.move(x_position, y_position)
        except Exception:
            pass
        # =========================================================================

        main_window.show()

        # =========================================================================
        # SESSİZ VE ERKEN TARAMAYI ÖNLEYEN FONT APPLIER (KONSOLU TEMİZ TUTAR)
        # =========================================================================
        f_conf = load_external_font_config()
        custom_qt6_font = QFont(f_conf["font_family"], f_conf["menu_size"])
        custom_qt6_font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        app.setFont(custom_qt6_font)

        try:
            target_menu = main_window.menubar if hasattr(main_window, 'menubar') else (main_window.menuBar() if hasattr(main_window, 'menuBar') else None)
            if target_menu:
                target_menu.setFont(custom_qt6_font)
        except Exception:
            pass
        # =========================================================================

    if should_show_initial_setup:
        QTimer.singleShot(
            0, lambda: InitialSetupController(app.getWindow()).exec())
    else:
        reporting_coordinator = ReportingCoordinator(app.getWindow())
        app._reporting_coordinator = reporting_coordinator
        QTimer.singleShot(0, reporting_coordinator.show_prepared_crash)

    app.aboutToQuit.connect(crash_session_monitor.mark_shutdown)
    app.aboutToQuit.connect(NotificationService.shutdown)
    app.aboutToQuit.connect(system_dictionary_provisioner.close)
    if desktop_application_dbus is not None:
        app.aboutToQuit.connect(desktop_application_dbus.stop)
    app.aboutToQuit.connect(ThemeManager.stop)
    app.aboutToQuit.connect(app.shutdownInterface)
    if unix_signal_bridge is not None:
        unix_signal_bridge.close()

    crash_session_monitor.mark_running()
    exit_code = app.exec()

    crash_session_monitor.mark_shutdown()
    NotificationService.shutdown()
    ThemeManager.stop()
    app.shutdownInterface()
    if unix_signal_bridge is not None:
        unix_signal_bridge.close()

    probe.record("session_end", phase="clean-exit")
    probe.close()
    crash_session_monitor.close()

    return exit_code
