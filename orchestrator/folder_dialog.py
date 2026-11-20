"""Native folder picker for the interface's "Browse…" button.

A web page cannot learn the full path of a folder the user picks: browsers
hide it on purpose. The orchestrator runs on the user's own desktop, so it
opens the standard Windows folder dialog itself and returns the path.

Only the API's loopback listener can trigger this, and only with a JSON body
(see api.py), so another website cannot open dialogs on the desktop.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DIALOG_TITLE = "Choose a folder to connect to Local Workbench"


def choose_folder_with_dialog(start_folder: str | None = None) -> str | None:
    """Show a folder dialog and return the chosen folder's absolute path.

    Blocks until the user chooses or cancels, so call it from a worker thread.

    Args:
        start_folder: Folder the dialog opens in, if it exists.

    Returns:
        The canonical Windows path, or None if the user cancelled.
    """
    # Imported here: tkinter is only needed when the dialog is used, and a
    # missing Tk installation must not stop the orchestrator starting.
    import tkinter
    from tkinter import filedialog

    root = tkinter.Tk()
    try:
        root.withdraw()
        # Without topmost the dialog can open behind the browser window.
        root.attributes("-topmost", True)
        initial_directory = (
            start_folder if start_folder and Path(start_folder).is_dir() else None
        )
        chosen = filedialog.askdirectory(
            parent=root,
            title=DIALOG_TITLE,
            mustexist=True,
            initialdir=initial_directory,
        )
    finally:
        root.destroy()
    if not chosen:
        logger.info("Folder dialog cancelled")
        return None
    # tkinter returns forward slashes; the rest of the system uses the
    # canonical Windows form.
    return str(Path(chosen).resolve())
