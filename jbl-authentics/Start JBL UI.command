#!/bin/bash
# Double-click this file to start the JBL Authentics UI.
# Keep it in the same folder as jbl_ui.py. Close the Terminal window to stop the UI.
cd "$(dirname "$0")" || exit 1
echo "Starting the JBL Authentics UI (this window has to stay open)..."
python3 jbl_ui.py
status=$?
if [ $status -ne 0 ]; then
  echo
  echo "python3 exited with status $status."
  echo "If macOS just offered to install the command line tools, let it finish, then double-click this file again."
  read -r -p "Press Return to close this window."
fi
