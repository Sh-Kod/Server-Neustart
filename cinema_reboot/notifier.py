"""
Lokale Benachrichtigungen – Windows-Notification + Warnton.

Nur aktiv unter Windows. Auf anderen Plattformen (Entwickler-PC unter Linux/Mac)
wird nur ein Log-Eintrag erzeugt.
"""
import logging
import platform
import sys

logger = logging.getLogger(__name__)


def play_alarm_sound() -> None:
    """Spielt einen Warnton ab."""
    system = platform.system()
    if system == "Windows":
        try:
            import winsound
            # 3× kurzer Ton (880 Hz, 400ms)
            for _ in range(3):
                winsound.Beep(880, 400)
        except Exception as e:
            logger.warning(f"Warnton konnte nicht abgespielt werden: {e}")
    else:
        # Auf Linux/Mac: Terminal-Bell
        sys.stdout.write("\a")
        sys.stdout.flush()
        logger.debug("Alarm-Sound: Terminal-Bell (Non-Windows)")


def send_windows_notification(title: str, message: str) -> None:
    """Sendet eine Windows-Desktop-Benachrichtigung."""
    system = platform.system()
    if system == "Windows":
        try:
            from winotify import Notification, audio
            toast = Notification(
                app_id="Cinema Reboot",
                title=title,
                msg=message,
                duration="long",
            )
            toast.set_audio(audio.Default, loop=False)
            toast.show()
        except ImportError:
            logger.warning(
                "winotify nicht installiert. Bitte 'pip install winotify' ausführen."
            )
        except Exception as e:
            logger.warning(f"Windows-Benachrichtigung fehlgeschlagen: {e}")
    else:
        logger.debug(f"[Notification – Non-Windows] {title}: {message}")


def raise_playback_alarm(cinema_name: str, enabled: bool = True) -> None:
    """
    Löst Alarm aus, wenn Playback blockiert hat (rote Grenze!).
    Kombination aus Ton + Windows-Notification.
    """
    if not enabled:
        return
    title = "⛔ REBOOT ABGEBROCHEN"
    message = f"{cinema_name}: Playback läuft! Kein Reboot durchgeführt."
    logger.warning(f"LOKALER ALARM: {title} – {message}")
    play_alarm_sound()
    send_windows_notification(title, message)
