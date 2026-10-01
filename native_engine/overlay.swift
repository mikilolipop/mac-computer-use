import Foundation
import AppKit
import CoreGraphics

// MARK: - Overlay View

class OverlayView: NSView {
    var accentColor = NSColor(red: 0x33/255.0, green: 0x9c/255.0, blue: 0xff/255.0, alpha: 0.95)
    var statusText = "ChatGPT is using your computer"
    var subText = "Esc to cancel"

    override func draw(_ dirtyRect: NSRect) {
        super.draw(dirtyRect)

        // 1. Draw outer glowing border
        let borderRect = bounds.insetBy(dx: 2.5, dy: 2.5)
        let borderPath = NSBezierPath(roundedRect: borderRect, xRadius: 12, yRadius: 12)
        borderPath.lineWidth = 3.5
        accentColor.setStroke()
        borderPath.stroke()

        // 2. Draw top floating badge/pill
        let pillWidth: CGFloat = 330
        let pillHeight: CGFloat = 34
        let pillX = (bounds.width - pillWidth) / 2.0
        let pillY = bounds.height - pillHeight - 12

        let pillRect = NSRect(x: pillX, y: pillY, width: pillWidth, height: pillHeight)
        let pillPath = NSBezierPath(roundedRect: pillRect, xRadius: 17, yRadius: 17)

        // Fill background with frosted dark glass
        NSColor(calibratedRed: 0.08, green: 0.09, blue: 0.12, alpha: 0.94).setFill()
        pillPath.fill()

        // Pill border
        accentColor.withAlphaComponent(0.6).setStroke()
        pillPath.lineWidth = 1.2
        pillPath.stroke()

        // 3. Draw indicator dot
        let dotDiameter: CGFloat = 8
        let dotRect = NSRect(x: pillX + 14, y: pillY + (pillHeight - dotDiameter) / 2.0, width: dotDiameter, height: dotDiameter)
        let dotPath = NSBezierPath(ovalIn: dotRect)
        accentColor.setFill()
        dotPath.fill()

        // 4. Draw Title Text
        let titleAttrs: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: 12.5, weight: .semibold),
            .foregroundColor: NSColor.white
        ]
        let titlePoint = NSPoint(x: pillX + 28, y: pillY + 8)
        (statusText as NSString).draw(at: titlePoint, withAttributes: titleAttrs)

        // 5. Draw Subtext (Esc to cancel)
        let subAttrs: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: 11.5, weight: .regular),
            .foregroundColor: NSColor(white: 0.7, alpha: 1.0)
        ]
        let subPoint = NSPoint(x: pillX + pillWidth - 90, y: pillY + 9)
        (subText as NSString).draw(at: subPoint, withAttributes: subAttrs)
    }
}

// MARK: - Window Finder Helper

func findWindowBounds(for pid: pid_t) -> CGRect? {
    guard let windowListInfo = CGWindowListCopyWindowInfo([.optionAll, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] else {
        return nil
    }

    var maxArea: CGFloat = 0
    var bestBounds: CGRect?

    for window in windowListInfo {
        if let windowPID = window[kCGWindowOwnerPID as String] as? pid_t, windowPID == pid {
            let layer = (window[kCGWindowLayer as String] as? Int) ?? -1
            if layer == 0 {
                if let boundsDict = window[kCGWindowBounds as String] as? [String: Any] {
                    var rect = CGRect.zero
                    if CGRectMakeWithDictionaryRepresentation(boundsDict as CFDictionary, &rect) {
                        let area = rect.width * rect.height
                        if area > maxArea && area > 10000 {
                            maxArea = area
                            bestBounds = rect
                        }
                    }
                }
            }
        }
    }
    return bestBounds
}

func findAppPID(named identifier: String) -> pid_t? {
    let apps = NSWorkspace.shared.runningApplications
    if let app = apps.first(where: { $0.localizedName?.caseInsensitiveCompare(identifier) == .orderedSame ||
                                     $0.bundleIdentifier?.caseInsensitiveCompare(identifier) == .orderedSame ||
                                     $0.localizedName?.localizedCaseInsensitiveContains(identifier) == true }) {
        return app.processIdentifier
    }
    return nil
}

// MARK: - Application Delegate

class AppDelegate: NSObject, NSApplicationDelegate {
    var panel: NSPanel?
    var targetApp: String = "Microsoft Edge"
    var duration: Double = 5.0
    var customText: String = "ChatGPT is using your computer"

    func applicationDidFinishLaunching(_ notification: Notification) {
        guard let pid = findAppPID(named: targetApp),
              let cgBounds = findWindowBounds(for: pid) else {
            fputs("Could not locate main window for app: \(targetApp)\n", stderr)
            exit(1)
        }

        guard let primaryScreen = NSScreen.screens.first else {
            fputs("No screen found\n", stderr)
            exit(1)
        }

        guard cgBounds.width > 0, cgBounds.height > 0,
              cgBounds.origin.x.isFinite, cgBounds.origin.y.isFinite else {
            fputs("Invalid window bounds for overlay\n", stderr)
            exit(1)
        }

        let screenHeight = primaryScreen.frame.height
        let nsY = screenHeight - cgBounds.origin.y - cgBounds.height
        let windowFrame = NSRect(x: cgBounds.origin.x, y: nsY, width: cgBounds.width, height: cgBounds.height)

        let overlayPanel = NSPanel(
            contentRect: windowFrame,
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )

        overlayPanel.isOpaque = false
        overlayPanel.backgroundColor = .clear
        overlayPanel.level = .floating
        overlayPanel.ignoresMouseEvents = true // Pass clicks right through to the app underneath!
        overlayPanel.hasShadow = true
        overlayPanel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]

        let customView = OverlayView(frame: NSRect(origin: .zero, size: windowFrame.size))
        customView.statusText = customText
        overlayPanel.contentView = customView

        overlayPanel.orderFrontRegardless()
        self.panel = overlayPanel

        fputs("Overlay displayed on \(targetApp) [\(Int(windowFrame.width))x\(Int(windowFrame.height))]\n", stderr)

        // Global Esc Key monitor to dismiss immediately
        NSEvent.addGlobalMonitorForEvents(matching: .keyDown) { event in
            if event.keyCode == 53 { // ESC
                fputs("ESC pressed by user - dismiss overlay\n", stderr)
                NSApp.terminate(nil)
            }
        }

        // Auto dismiss timer
        if duration > 0 {
            DispatchQueue.main.asyncAfter(deadline: .now() + duration) {
                NSApp.terminate(nil)
            }
        }
    }
}

// MARK: - CLI Entrypoint

let app = NSApplication.shared
let delegate = AppDelegate()

var i = 1
while i < CommandLine.arguments.count {
    let arg = CommandLine.arguments[i]
    if arg == "--app", i + 1 < CommandLine.arguments.count {
        delegate.targetApp = CommandLine.arguments[i + 1]
        i += 2
    } else if arg == "--duration", i + 1 < CommandLine.arguments.count {
        delegate.duration = Double(CommandLine.arguments[i + 1]) ?? 5.0
        i += 2
    } else if arg == "--text", i + 1 < CommandLine.arguments.count {
        delegate.customText = CommandLine.arguments[i + 1]
        i += 2
    } else {
        i += 1
    }
}

app.delegate = delegate
app.run()
