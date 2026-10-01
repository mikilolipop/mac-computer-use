#!/usr/bin/env python3
import subprocess
import time
import sys

def send_cad_commands(commands, delay=0.3):
    script_parts = [
        'tell application id "com.autodesk.AutoCAD2026" to activate',
        'delay 0.3',
        'tell application "System Events" to tell process "AutoCAD"'
    ]
    for cmd in commands:
        if cmd == "<ESC>":
            script_parts.append('  key code 53')
            script_parts.append(f'  delay {delay}')
        elif cmd == "<ENTER>":
            script_parts.append('  key code 36')
            script_parts.append(f'  delay {delay}')
        else:
            # Escape double quotes and backslashes
            escaped = cmd.replace('\\', '\\\\').replace('"', '\\"')
            script_parts.append(f'  keystroke "{escaped}" & return')
            script_parts.append(f'  delay {delay}')
    script_parts.append('end tell')
    
    osa = '\n'.join(script_parts)
    res = subprocess.run(['osascript', '-e', osa], capture_output=True, text=True)
    if res.returncode != 0:
        print("Error sending commands:", res.stderr, file=sys.stderr)
        return False
    return True

if __name__ == "__main__":
    # Test clearing and drawing region nut
    test_cmds = [
        "<ESC>", "<ESC>",
        "_ERASE", "_ALL", "<ENTER>", "<ENTER>",
        "_POLYGON", "6", "0,0", "_C", "12",
        "_CIRCLE", "0,0", "8",
        "_REGION", "_ALL", "<ENTER>", "<ENTER>",
        "_SUBTRACT", "0,12", "<ENTER>", "0,0", "<ENTER>",
        "_EXTRUDE", "_ALL", "<ENTER>", "13",
        "_VPOINT", "1,-1,1",
        "_SHADEMODE", "_C",
        "_ZOOM", "_E"
    ]
    ok = send_cad_commands(test_cmds, delay=0.25)
    print("Commands sent successfully:", ok)
