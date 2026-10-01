import Foundation
import AppKit
import ApplicationServices
import CoreGraphics
import UniformTypeIdentifiers
import Vision
import CryptoKit

// MARK: - Data Models

struct AppInfoItem: Codable {
    let pid: pid_t
    let bundleId: String?
    let name: String
    let isActive: Bool
}

struct ElementBounds: Codable, Equatable {
    let x: Double
    let y: Double
    let width: Double
    let height: Double
}

struct ParsedElement: Codable, Equatable {
    let index: Int
    let role: String
    let title: String?
    let value: String?
    let desc: String?
    let actions: [String]
    let bounds: ElementBounds?
    var identifier: String? = nil
}

struct StateResponse: Codable {
    let app: String
    let pid: pid_t
    let windowId: CGWindowID?
    let windowBounds: ElementBounds?
    let text: String
    let diff: String?
    let screenshotUrl: String?
    let elementCount: Int
    var elements: [ParsedElement]? = nil
    var snapshotId: String? = nil
    var sessionId: String? = nil
    var timingsMs: [String: Double]? = nil
    var webAXStatus: String? = nil
    var isTruncated: Bool? = nil
}

struct DoctorResponse: Codable {
    let success: Bool
    let accessibility: Bool
    let screenCapture: Bool
    let osVersion: String
    let arch: String
    let binaryPath: String
    let advice: [String]
}

struct TextMatchResult: Codable {
    let text: String
    let desktopX: Double
    let desktopY: Double
    let confidence: Float
    let bounds: ElementBounds
}

struct OCRMatch: Codable {
    let text: String
    let confidence: Float
    let bounds: ElementBounds
    let desktopX: Double
    let desktopY: Double
}

struct OCRWindowFrame: Codable {
    let windowID: CGWindowID
    let pid: pid_t
    let timestamp: Double
    let windowBounds: ElementBounds
    let matches: [OCRMatch]
}

struct GenericResponse: Codable {
    let success: Bool
    var error: String? = nil
    var action: String? = nil
    var pid: pid_t? = nil
    var clickedIndex: Int? = nil
    var x: Double? = nil
    var y: Double? = nil
    var element: Int? = nil
    var value: String? = nil
    var key: String? = nil
    var app: String? = nil
    var navigatedTo: String? = nil
    var executed: Int? = nil
    var failedIndex: Int? = nil
    var foundText: String? = nil
    var desktopX: Double? = nil
    var desktopY: Double? = nil
    var message: String? = nil
    var text: String? = nil
    var code: String? = nil
    var status: String? = nil
    var confidence: Float? = nil
    var bounds: ElementBounds? = nil
    var matchCount: Int? = nil
    var matches: [OCRMatch]? = nil
    var direction: String? = nil
    var amount: Int? = nil
}

struct ActionItem: Codable {
    let action: String
    let element: Int?
    let value: String?
    let text: String?
    let message: String?
    let key: String?
    let url: String?
    let x: Double?
    let y: Double?
    let waitMs: UInt32?
    let exact: Bool?
    let newChat: Bool?
    let pressReturn: Bool?
    let direction: String?
    let amount: Int?
    let modifiers: [String]?
    let occurrence: Int?
    let minConfidence: Float?
}

// MARK: - JSON Output Helper

func outputJSON<T: Encodable>(_ object: T, pretty: Bool = false) {
    let encoder = JSONEncoder()
    if pretty {
        encoder.outputFormatting = [.prettyPrinted]
    }
    if let data = try? encoder.encode(object), let str = String(data: data, encoding: .utf8) {
        print(str)
    } else {
        fputs("{\"success\": false, \"error\": \"Failed to serialize JSON output\"}\n", stderr)
    }
}

// MARK: - Cache Helpers

let sessionID = ProcessInfo.processInfo.environment["MAC_CUA_SESSION"] ?? "cli"
let cacheDir: URL = {
    let digest = SHA256.hash(data: Data(sessionID.utf8)).map { String(format: "%02x", $0) }.joined()
    let dir = URL(fileURLWithPath: NSTemporaryDirectory()).appendingPathComponent("mac-cua/" + digest)
    try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
    return dir
}()

func pruneStaleCacheFiles(maxAgeSeconds: TimeInterval = 1800) {
    let fm = FileManager.default
    guard let files = try? fm.contentsOfDirectory(at: cacheDir, includingPropertiesForKeys: [.contentModificationDateKey]) else { return }
    let cutoff = Date(timeIntervalSinceNow: -maxAgeSeconds)
    for file in files {
        if let attrs = try? file.resourceValues(forKeys: [.contentModificationDateKey]),
           let modDate = attrs.contentModificationDate,
           modDate < cutoff {
            try? fm.removeItem(at: file)
        }
    }
}

func pruneOldSessionDirs(maxAgeSeconds: TimeInterval = 86400) {
    let fm = FileManager.default
    let base = URL(fileURLWithPath: NSTemporaryDirectory()).appendingPathComponent("mac-cua")
    guard let entries = try? fm.contentsOfDirectory(at: base, includingPropertiesForKeys: [.contentModificationDateKey]) else { return }
    let cutoff = Date(timeIntervalSinceNow: -maxAgeSeconds)
    for entry in entries {
        if let attrs = try? entry.resourceValues(forKeys: [.contentModificationDateKey]),
           let modDate = attrs.contentModificationDate,
           modDate < cutoff {
            try? fm.removeItem(at: entry)
        }
    }
}

func cacheURL(for app: String, type: String) -> URL {
    let key = SHA256.hash(data: Data(app.utf8)).map { String(format: "%02x", $0) }.joined()
    return cacheDir.appendingPathComponent("\(key)_\(type).json")
}

struct Snapshot: Codable {
    let id: String
    let session: String
    let pid: pid_t
    let launchedAt: Double
    let windowID: CGWindowID
    let bounds: ElementBounds
    let createdAt: Double
    let elements: [ParsedElement]
    var maxNodes: Int? = 1000
    var maxDepth: Int? = 20
    var isTruncated: Bool? = false
}

func snapshotURL(_ id: String) -> URL? {
    guard let uuid = UUID(uuidString: id) else { return nil }
    return cacheDir.appendingPathComponent("snapshot_" + uuid.uuidString + ".json")
}

func cliOption(_ name: String) -> String? {
    let args = CommandLine.arguments
    guard let i = args.firstIndex(of: name), i + 1 < args.count else { return nil }
    return args[i + 1]
}

var actionError: String? = nil

func safeAXApplication(_ pid: pid_t, timeoutSeconds: Float = 1.5) -> AXUIElement {
    let app = AXUIElementCreateApplication(pid)
    _ = AXUIElementSetMessagingTimeout(app, timeoutSeconds)
    return app
}

func focusedScope(_ pid: pid_t) -> AXUIElement? {
    if let raw = cliOption("--window-id") {
        guard let wanted = UInt32(raw) else { return nil }
        var value: AnyObject?
        AXUIElementCopyAttributeValue(safeAXApplication(pid), kAXWindowsAttribute as CFString, &value)
        let matches = (value as? [AXUIElement] ?? []).filter {
            guard let bounds = getElementBounds($0) else { return false }
            return scopedWindowID(pid, bounds) == wanted
        }
        return matches.count == 1 ? matches[0] : nil
    }
    let app = safeAXApplication(pid)
    var value: AnyObject?
    if AXUIElementCopyAttributeValue(app, kAXFocusedWindowAttribute as CFString, &value) == .success,
       let value = value, CFGetTypeID(value) == AXUIElementGetTypeID() {
        return (value as! AXUIElement)
    }
    var windows: AnyObject?
    if AXUIElementCopyAttributeValue(app, kAXWindowsAttribute as CFString, &windows) == .success,
       let items = windows as? [AXUIElement], items.count == 1 { return items[0] }
    return nil // Ambiguous scope must never fall back to all windows.
}

// Explicit window input never falls back to whichever window happens to be focused.
func inputWindowIsFocused(_ pid: pid_t?) -> Bool {
    guard let raw = cliOption("--window-id") else { return true }
    guard let wanted = UInt32(raw), let pid = pid,
          NSRunningApplication(processIdentifier: pid)?.isActive == true else { return false }
    var value: AnyObject?
    guard AXUIElementCopyAttributeValue(safeAXApplication(pid), kAXFocusedWindowAttribute as CFString, &value) == .success,
          let value = value, CFGetTypeID(value) == AXUIElementGetTypeID(),
          let bounds = getElementBounds(value as! AXUIElement) else { return false }
    return scopedWindowID(pid, bounds) == wanted
}

func activateSelectedWindow(_ app: NSRunningApplication) -> Bool {
    if cliOption("--window-id") == nil { app.activate(); usleep(120000); return app.isActive }
    guard let scope = focusedScope(app.processIdentifier) else { return false }
    app.activate()
    guard AXUIElementPerformAction(scope, kAXRaiseAction as CFString) == .success else { return false }
    _ = AXUIElementSetAttributeValue(scope, kAXMainAttribute as CFString, kCFBooleanTrue)
    usleep(120000)
    return inputWindowIsFocused(app.processIdentifier)
}

func scopedWindowID(_ pid: pid_t, _ bounds: ElementBounds) -> CGWindowID? {
    guard let windows = CGWindowListCopyWindowInfo([.optionAll, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] else { return nil }
    let matches = windows.filter { win in
        guard (win[kCGWindowOwnerPID as String] as? pid_t) == pid,
              (win[kCGWindowLayer as String] as? Int) == 0,
              let b = win[kCGWindowBounds as String] as? [String: Double] else { return false }
        return abs((b["X"] ?? .infinity) - bounds.x) < 1 && abs((b["Y"] ?? .infinity) - bounds.y) < 1 &&
               abs((b["Width"] ?? .infinity) - bounds.width) < 1 && abs((b["Height"] ?? .infinity) - bounds.height) < 1
    }
    return matches.count == 1 ? matches[0][kCGWindowNumber as String] as? CGWindowID : nil
}

// Ignore unrelated animation, but never treat a role or list offset as identity.
func sameTargetIdentity(_ cached: ParsedElement, _ live: ParsedElement) -> Bool {
    guard cached.role == live.role, cached.title == live.title, cached.desc == live.desc,
          cached.actions.sorted() == live.actions.sorted() else { return false }
    let hasID = !(cached.identifier ?? "").isEmpty
    if hasID {
        guard cached.identifier == live.identifier else { return false }
    } else {
        // Without a stable ID, require a meaningful label and unchanged geometry.
        guard !(cached.title ?? "").isEmpty || !(cached.desc ?? "").isEmpty,
              cached.bounds == live.bounds else { return false }
    }
    let editable = ["AXTextField", "AXTextArea", "AXComboBox", "AXSearchField"].contains(cached.role)
    return editable || cached.value == live.value
}

func resolveSnapshotTarget(_ snap: Snapshot, pid: pid_t, launchedAt: Double, windowID: CGWindowID,
                           bounds: ElementBounds, elements: [ParsedElement], targetIndex: Int, now: Double) -> Int? {
    guard snap.session == sessionID, snap.pid == pid, snap.launchedAt == launchedAt,
          snap.windowID == windowID, snap.bounds == bounds,
          now >= snap.createdAt, now - snap.createdAt <= 120,
          targetIndex > 0, let cached = snap.elements.first(where: { $0.index == targetIndex }) else { return nil }
    // Reject ambiguous targets in either snapshot, even when the ordinal matches.
    guard snap.elements.filter({ sameTargetIdentity(cached, $0) }).count == 1 else { return nil }
    let candidates = elements.enumerated().filter { sameTargetIdentity(cached, $0.element) }
    return candidates.count == 1 ? candidates[0].offset : nil
}

func snapshotMatches(_ snap: Snapshot, pid: pid_t, launchedAt: Double, windowID: CGWindowID,
                     bounds: ElementBounds, elements: [ParsedElement], targetIndex: Int = 1, now: Double) -> Bool {
    resolveSnapshotTarget(snap, pid: pid, launchedAt: launchedAt, windowID: windowID,
                          bounds: bounds, elements: elements, targetIndex: targetIndex, now: now) != nil
}

// MARK: - App Resolution

func findRunningApp(named identifier: String) -> NSRunningApplication? {
    let workspace = NSWorkspace.shared
    let allApps = workspace.runningApplications

    let isDisqualified: (NSRunningApplication) -> Bool = { app in
        let bId = app.bundleIdentifier?.lowercased() ?? ""
        let name = app.localizedName?.lowercased() ?? ""
        if identifier.contains(".") { return false } // caller provided explicit bundleId
        if bId.contains("findersync") || bId.contains("extension") || bId.contains("helper") || bId.contains("xpc") || bId.contains("crashpad") {
            return true
        }
        if name.contains("extension") || name.contains("helper") || name.contains("service") {
            return true
        }
        return false
    }

    // 1. Primary pool: regular GUI applications (Dock / Menubar / Windows)
    let regularApps = allApps.filter { $0.activationPolicy == .regular && !isDisqualified($0) }

    // 1a. Exact bundle identifier in regular apps
    if let app = regularApps.first(where: { $0.bundleIdentifier?.caseInsensitiveCompare(identifier) == .orderedSame }) {
        return app
    }
    // 1b. Exact localized name in regular apps
    if let app = regularApps.first(where: { $0.localizedName?.caseInsensitiveCompare(identifier) == .orderedSame }) {
        return app
    }
    // 1c. Partial localized name in regular apps
    if let app = regularApps.first(where: { $0.localizedName?.localizedCaseInsensitiveContains(identifier) == true }) {
        return app
    }
    // 1d. Partial bundle identifier in regular apps
    if let app = regularApps.first(where: { $0.bundleIdentifier?.localizedCaseInsensitiveContains(identifier) == true }) {
        return app
    }
    // 1e. Executable filename match in regular apps
    if let app = regularApps.first(where: { $0.executableURL?.lastPathComponent.caseInsensitiveCompare(identifier) == .orderedSame }) {
        return app
    }

    // 2. Fallback pool: all running applications, sorted by non-disqualified and regular policy
    let fallbackPool = allApps.sorted { a, b in
        let aBad = isDisqualified(a)
        let bBad = isDisqualified(b)
        if aBad != bBad { return !aBad }
        return (a.activationPolicy == .regular ? 0 : 1) < (b.activationPolicy == .regular ? 0 : 1)
    }

    if let app = fallbackPool.first(where: { $0.bundleIdentifier?.caseInsensitiveCompare(identifier) == .orderedSame }) {
        return app
    }
    if let app = fallbackPool.first(where: { $0.localizedName?.caseInsensitiveCompare(identifier) == .orderedSame }) {
        return app
    }
    if let app = fallbackPool.first(where: { $0.localizedName?.localizedCaseInsensitiveContains(identifier) == true }) {
        return app
    }
    if let app = fallbackPool.first(where: { $0.bundleIdentifier?.localizedCaseInsensitiveContains(identifier) == true }) {
        return app
    }
    return nil
}

func resolveAppURL(named identifier: String) -> URL? {
    if identifier.hasPrefix("/") || identifier.hasSuffix(".app") {
        let url = URL(fileURLWithPath: identifier)
        if FileManager.default.fileExists(atPath: url.path) {
            return url
        }
    }
    if identifier.contains(".") {
        if let url = NSWorkspace.shared.urlForApplication(withBundleIdentifier: identifier) {
            return url
        }
    }
    let candidateFolders = [
        "/Applications",
        "/System/Applications",
        "/System/Applications/Utilities",
        NSHomeDirectory() + "/Applications"
    ]
    let fm = FileManager.default
    for folder in candidateFolders {
        let target = folder + "/\(identifier).app"
        if fm.fileExists(atPath: target) {
            return URL(fileURLWithPath: target)
        }
    }
    for folder in candidateFolders {
        guard let contents = try? fm.contentsOfDirectory(atPath: folder) else { continue }
        for item in contents where item.hasSuffix(".app") {
            let baseName = String(item.dropLast(4))
            if baseName.caseInsensitiveCompare(identifier) == .orderedSame {
                return URL(fileURLWithPath: folder + "/\(item)")
            }
        }
    }
    return nil
}

func launchApplicationByName(_ name: String) -> Bool {
    if let url = resolveAppURL(named: name) {
        if #available(macOS 10.15, *) {
            let config = NSWorkspace.OpenConfiguration()
            config.activates = true
            let sema = DispatchSemaphore(value: 0)
            var launched = false
            NSWorkspace.shared.openApplication(at: url, configuration: config) { app, error in
                launched = (app != nil && error == nil)
                sema.signal()
            }
            _ = sema.wait(timeout: .now() + 5.0)
            if launched { return true }
        }
    }
    let proc = Process()
    proc.executableURL = URL(fileURLWithPath: "/usr/bin/open")
    proc.arguments = ["-a", name]
    do {
        try proc.run()
        let deadline = ProcessInfo.processInfo.systemUptime + 5.0
        while proc.isRunning && ProcessInfo.processInfo.systemUptime < deadline { usleep(10000) }
        if proc.isRunning {
            proc.terminate()
            return false
        }
        return proc.terminationStatus == 0
    } catch {
        return false
    }
}

// MARK: - Unified AXTree Traversal & Filtering Logic

func isIgnoredRole(_ role: String) -> Bool {
    return role == "AXGrowArea" || role == "AXSplitter"
}

func getElementBounds(_ element: AXUIElement) -> ElementBounds? {
    var posVal: AnyObject?
    var sizeVal: AnyObject?
    if AXUIElementCopyAttributeValue(element, kAXPositionAttribute as CFString, &posVal) == .success,
       AXUIElementCopyAttributeValue(element, kAXSizeAttribute as CFString, &sizeVal) == .success {
        var pt = CGPoint.zero
        var sz = CGSize.zero
        if let posVal = posVal, CFGetTypeID(posVal) == AXValueGetTypeID() {
            AXValueGetValue(posVal as! AXValue, .cgPoint, &pt)
        }
        if let sizeVal = sizeVal, CFGetTypeID(sizeVal) == AXValueGetTypeID() {
            AXValueGetValue(sizeVal as! AXValue, .cgSize, &sz)
        }
        if sz.width > 0 && sz.height > 0 {
            return ElementBounds(x: Double(pt.x), y: Double(pt.y), width: Double(sz.width), height: Double(sz.height))
        }
    }
    return nil
}

func isInteractiveElement(role: String, actions: [String], bounds: ElementBounds?) -> Bool {
    guard bounds != nil else { return false }
    if !actions.isEmpty { return true }
    let interactiveRoles = [
        "Button", "TextField", "TextArea", "CheckBox", "RadioButton",
        "PopUpButton", "MenuItem", "MenuButton", "Tab", "Link", "Row",
        "ComboBox", "SearchField", "SecureTextField"
    ]
    return interactiveRoles.contains(where: { role.contains($0) })
}

func probeHasWebArea(element: AXUIElement, depth: Int = 0, maxDepth: Int = 6) -> Bool {
    if depth > maxDepth { return false }
    var roleVal: AnyObject?
    guard AXUIElementCopyAttributeValue(element, kAXRoleAttribute as CFString, &roleVal) == .success,
          let role = roleVal as? String else { return false }
    if role == "AXWebArea" { return true }
    var childrenVal: AnyObject?
    guard AXUIElementCopyAttributeValue(element, kAXChildrenAttribute as CFString, &childrenVal) == .success,
          let children = childrenVal as? [AXUIElement] else { return false }
    for child in children {
        if probeHasWebArea(element: child, depth: depth + 1, maxDepth: maxDepth) {
            return true
        }
    }
    return false
}

class TreeCollector {
    var elements: [ParsedElement] = []
    var textLines: [String] = []
    var liveElements: [AXUIElement] = []
    private var currentIndex = 1
    var compact: Bool = false
    var hasWebArea = false
    var maxNodes: Int = 1000
    private var visitedNodes = 0
    var isTruncated = false

    func collect(element: AXUIElement, depth: Int = 0, maxDepth: Int = 20) {
        if depth > maxDepth || visitedNodes >= maxNodes {
            if visitedNodes >= maxNodes {
                isTruncated = true
            }
            return
        }
        visitedNodes += 1

        var roleValue: AnyObject?
        AXUIElementCopyAttributeValue(element, kAXRoleAttribute as CFString, &roleValue)
        let role = (roleValue as? String) ?? "AXUnknown"
        if role == "AXWebArea" { hasWebArea = true }
        if isIgnoredRole(role) { return }

        var titleValue: AnyObject?
        AXUIElementCopyAttributeValue(element, kAXTitleAttribute as CFString, &titleValue)
        let title = titleValue as? String

        var valueVal: AnyObject?
        AXUIElementCopyAttributeValue(element, kAXValueAttribute as CFString, &valueVal)
        let valueStr = valueVal != nil ? "\(valueVal!)" : nil

        var descValue: AnyObject?
        AXUIElementCopyAttributeValue(element, kAXDescriptionAttribute as CFString, &descValue)
        let desc = descValue as? String

        var actionsValue: CFArray?
        AXUIElementCopyActionNames(element, &actionsValue)
        let actions = (actionsValue as? [String]) ?? []

        let bounds = getElementBounds(element)
        let isInteractive = isInteractiveElement(role: role, actions: actions, bounds: bounds)

        let hasMeaningfulContent = (title != nil && !title!.isEmpty) ||
                                  (desc != nil && !desc!.isEmpty) ||
                                  (valueStr != nil && !valueStr!.isEmpty && valueStr != title)

        let isStructuralNoise = !isInteractive && !hasMeaningfulContent && (role == "AXGroup" || role == "AXGenericElement" || role == "AXScrollArea" || role == "AXUnknown" || role == "AXSplitGroup")

        if isInteractive && bounds != nil {
            let idx = currentIndex
            currentIndex += 1

            let parsed = ParsedElement(
                index: idx,
                role: role,
                title: title,
                value: valueStr,
                desc: desc,
                actions: actions,
                bounds: bounds
            )
            var identified = parsed
            var identifier: AnyObject?
            AXUIElementCopyAttributeValue(element, kAXIdentifierAttribute as CFString, &identifier)
            identified.identifier = identifier as? String
            elements.append(identified)
            liveElements.append(element)

            let indent = String(repeating: "  ", count: depth)
            var line = "\(indent)[\(idx)] \(role)"
            if let t = title, !t.isEmpty {
                line += ": '\(t)'"
            } else if let d = desc, !d.isEmpty {
                line += " (\(d))"
            }
            if let v = valueStr, !v.isEmpty && v != title {
                let truncated = v.count > 500 ? String(v.prefix(497)) + "..." : v
                line += " (value: '\(truncated)')"
            }
            textLines.append(line)
        } else if !(compact && isStructuralNoise) {
            let indent = String(repeating: "  ", count: depth)
            var line = "\(indent)\(role)"

            if let t = title, !t.isEmpty {
                line += ": '\(t)'"
            } else if let d = desc, !d.isEmpty {
                line += " (\(d))"
            }

            if let v = valueStr, !v.isEmpty && v != title {
                let truncated = v.count > 500 ? String(v.prefix(497)) + "..." : v
                line += " (value: '\(truncated)')"
            }

            textLines.append(line)
        }

        var childrenValue: AnyObject?
        let result = AXUIElementCopyAttributeValue(element, kAXChildrenAttribute as CFString, &childrenValue)
        if result == .success, let children = childrenValue as? [AXUIElement] {
            for child in children {
                if visitedNodes >= maxNodes {
                    isTruncated = true
                    break
                }
                autoreleasepool {
                    collect(element: child, depth: depth + 1, maxDepth: maxDepth)
                }
            }
        }
    }
}

func findLiveElement(appPID: pid_t, targetIndex: Int) -> (element: AXUIElement, actions: [String])? {
    actionError = "STALE_SNAPSHOT: refresh get_app_state and pass snapshotId"
    guard let id = cliOption("--snapshot"), let url = snapshotURL(id),
          let data = try? Data(contentsOf: url), let snap = try? JSONDecoder().decode(Snapshot.self, from: data),
          snap.id == id, let app = NSRunningApplication(processIdentifier: appPID),
          let launch = app.launchDate?.timeIntervalSince1970,
          let scope = focusedScope(appPID), let bounds = getElementBounds(scope),
          let windowID = scopedWindowID(appPID, bounds) else { return nil }
    let collector = TreeCollector()
    collector.maxNodes = snap.maxNodes ?? 1000
    let depthToUse = snap.maxDepth ?? 20
    collector.collect(element: scope, maxDepth: depthToUse)
    guard let offset = resolveSnapshotTarget(snap, pid: appPID, launchedAt: launch, windowID: windowID,
                          bounds: bounds, elements: collector.elements, targetIndex: targetIndex, now: Date().timeIntervalSince1970),
          offset < collector.liveElements.count else { return nil }
    actionError = nil
    return (collector.liveElements[offset], collector.elements[offset].actions)
}

// MARK: - Screen Capture

func captureWindow(for pid: pid_t, targetBounds: ElementBounds? = nil, noShadow: Bool = true) -> (CGWindowID?, String?, ElementBounds?) {
    guard let windowListInfo = CGWindowListCopyWindowInfo([.optionAll, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] else {
        return (nil, nil, nil)
    }

    var bestWindowId: CGWindowID?
    var bestBounds: ElementBounds?
    var maxArea: Double = 0
    var matchedTarget = false

    for window in windowListInfo {
        if let windowPID = window[kCGWindowOwnerPID as String] as? pid_t, windowPID == pid {
            let layer = (window[kCGWindowLayer as String] as? Int) ?? -1
            if layer == 0 {
                if let boundsDict = window[kCGWindowBounds as String] as? [String: Any],
                   let x = boundsDict["X"] as? Double,
                   let y = boundsDict["Y"] as? Double,
                   let w = boundsDict["Width"] as? Double,
                   let h = boundsDict["Height"] as? Double {

                    if let target = targetBounds {
                        if abs(x - target.x) < 1 && abs(y - target.y) < 1 && abs(w - target.width) < 1 && abs(h - target.height) < 1 {
                            if let wId = window[kCGWindowNumber as String] as? CGWindowID {
                                matchedTarget = true
                                bestWindowId = wId
                                bestBounds = ElementBounds(x: x, y: y, width: w, height: h)
                                break
                            }
                        }
                    }

                    let area = w * h
                    if area > maxArea && area > 100 {
                        maxArea = area
                        if let wId = window[kCGWindowNumber as String] as? CGWindowID {
                            bestWindowId = wId
                            bestBounds = ElementBounds(x: x, y: y, width: w, height: h)
                        }
                    }
                }
            }
        }
    }

    guard targetBounds == nil || matchedTarget else { return (nil, nil, nil) }
    guard let windowId = bestWindowId else {
        return (nil, nil, nil)
    }

    let filePath = cacheDir.appendingPathComponent("cua_window_\(pid)_\(UUID().uuidString).png")

    let proc = Process()
    proc.executableURL = URL(fileURLWithPath: "/usr/sbin/screencapture")
    proc.arguments = noShadow ? ["-l", "\(windowId)", "-o", "-x", filePath.path] : ["-l", "\(windowId)", "-x", filePath.path]

    do {
        try proc.run()
        let deadline = ProcessInfo.processInfo.systemUptime + 3
        while proc.isRunning && ProcessInfo.processInfo.systemUptime < deadline { usleep(10000) }
        if proc.isRunning {
            proc.terminate()
            usleep(50000)
            if proc.isRunning { kill(proc.processIdentifier, SIGKILL) }
            proc.waitUntilExit()
            return (windowId, nil, bestBounds)
        }
        if proc.terminationStatus == 0 {
            return (windowId, filePath.path, bestBounds)
        }
    } catch {
        fputs("screencapture error: \(error)\n", stderr)
    }

    return (windowId, nil, bestBounds)
}

// MARK: - Native Vision OCR Engine with Frame Cache & Disambiguation

func ocrCacheURL(for windowID: CGWindowID) -> URL {
    return cacheDir.appendingPathComponent("ocr_\(windowID).json")
}

func invalidateOCRCache(for windowID: CGWindowID? = nil) {
    if let wid = windowID {
        try? FileManager.default.removeItem(at: ocrCacheURL(for: wid))
    } else {
        let fm = FileManager.default
        if let files = try? fm.contentsOfDirectory(at: cacheDir, includingPropertiesForKeys: nil) {
            for f in files where f.lastPathComponent.hasPrefix("ocr_") && f.lastPathComponent.hasSuffix(".json") {
                try? fm.removeItem(at: f)
            }
        }
    }
}

func boundsRoughlyEqual(_ a: ElementBounds, _ b: ElementBounds, tolerance: Double = 1.0) -> Bool {
    return abs(a.x - b.x) <= tolerance &&
           abs(a.y - b.y) <= tolerance &&
           abs(a.width - b.width) <= tolerance &&
           abs(a.height - b.height) <= tolerance
}

func ocrWindow(appPID: pid_t, forceRefresh: Bool = false) -> OCRWindowFrame? {
    guard let scope = focusedScope(appPID), let target = getElementBounds(scope),
          let windowId = scopedWindowID(appPID, target) else { return nil }
    let cacheFile = ocrCacheURL(for: windowId)
    if !forceRefresh,
       let cachedData = try? Data(contentsOf: cacheFile),
       let cached = try? JSONDecoder().decode(OCRWindowFrame.self, from: cachedData),
       cached.windowID == windowId, cached.pid == appPID,
       boundsRoughlyEqual(cached.windowBounds, target),
       (Date().timeIntervalSince1970 - cached.timestamp) < 3.0 {
        return cached
    }

    let (windowIdOpt, pathOpt, _) = captureWindow(for: appPID, targetBounds: target, noShadow: true)
    guard let capturedWindowId = windowIdOpt, let imagePath = pathOpt else { return nil }
    defer { try? FileManager.default.removeItem(atPath: imagePath) }

    guard let windowListInfo = CGWindowListCopyWindowInfo([.optionAll, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] else {
        return nil
    }
    var winBounds: (x: Double, y: Double, w: Double, h: Double)? = nil
    for win in windowListInfo {
        if let wid = win[kCGWindowNumber as String] as? CGWindowID, wid == capturedWindowId,
           let b = win[kCGWindowBounds as String] as? [String: Any],
           let x = b["X"] as? Double,
           let y = b["Y"] as? Double,
           let w = b["Width"] as? Double,
           let h = b["Height"] as? Double {
            winBounds = (x, y, w, h)
            break
        }
    }
    guard let wb = winBounds else { return nil }

    let url = URL(fileURLWithPath: imagePath)
    var allMatches: [OCRMatch] = []
    let request = VNRecognizeTextRequest { req, err in
        guard let obs = req.results as? [VNRecognizedTextObservation] else { return }
        for o in obs {
            guard let top = o.topCandidates(1).first else { continue }
            let str = top.string
            let box = o.boundingBox
            let relX = (box.origin.x + box.size.width / 2.0) * wb.w
            let relY = (1.0 - box.origin.y - box.size.height / 2.0) * wb.h
            let deskX = wb.x + relX
            let deskY = wb.y + relY
            let bounds = ElementBounds(
                x: wb.x + box.origin.x * wb.w,
                y: wb.y + (1.0 - box.origin.y - box.size.height) * wb.h,
                width: box.size.width * wb.w,
                height: box.size.height * wb.h
            )
            allMatches.append(OCRMatch(text: str, confidence: top.confidence, bounds: bounds, desktopX: deskX, desktopY: deskY))
        }
    }
    request.recognitionLanguages = ["zh-Hans", "en-US"]
    request.recognitionLevel = .accurate
    let handler = VNImageRequestHandler(url: url, options: [:])
    try? handler.perform([request])

    let result = OCRWindowFrame(windowID: windowId, pid: appPID, timestamp: Date().timeIntervalSince1970, windowBounds: target, matches: allMatches)
    if let data = try? JSONEncoder().encode(result) {
        try? data.write(to: cacheFile, options: .atomic)
    }
    return result
}

func findMatchesInWindow(appPID: pid_t, query: String, exact: Bool = false, minConfidence: Float = 0.0) -> [OCRMatch] {
    guard let frame = ocrWindow(appPID: appPID) else { return [] }
    return frame.matches.filter { match in
        guard match.confidence >= minConfidence else { return false }
        return exact ? (match.text.caseInsensitiveCompare(query) == .orderedSame)
                     : match.text.localizedCaseInsensitiveContains(query)
    }
}

func findTextInWindow(appPID: pid_t, query: String, exact: Bool = false) -> TextMatchResult? {
    let matches = findMatchesInWindow(appPID: appPID, query: query, exact: exact)
    guard let first = matches.first else { return nil }
    return TextMatchResult(text: first.text, desktopX: first.desktopX, desktopY: first.desktopY, confidence: first.confidence, bounds: first.bounds)
}

enum OCRError: Error {
    case notFound(String)
    case ambiguous(String, Int, [OCRMatch])
    case outOfBounds(Int, Int)
}

func resolveOCRTarget(
    appPID: pid_t,
    query: String,
    exact: Bool = false,
    occurrence: Int? = nil,
    minConfidence: Float = 0.0
) throws -> OCRMatch {
    let matches = findMatchesInWindow(appPID: appPID, query: query, exact: exact, minConfidence: minConfidence)
    if matches.isEmpty {
        throw OCRError.notFound(query)
    }
    if let occ = occurrence {
        guard occ >= 1 && occ <= matches.count else {
            throw OCRError.outOfBounds(occ, matches.count)
        }
        return matches[occ - 1]
    } else if matches.count > 1 {
        // P1-2: duplicate matches with exact=true (e.g. ["搜索", "搜索"]) are STILL ambiguous without explicit occurrence!
        throw OCRError.ambiguous(query, matches.count, matches)
    } else {
        return matches.first!
    }
}

// MARK: - Diff Computation

func computeDiff(oldLines: [String], newLines: [String]) -> String {
    if oldLines == newLines { return "(no visible UI changes)" }
    return newLines.difference(from: oldLines).map { change in
        switch change {
        case .insert(let offset, let line, _): return "+ [line \(offset + 1)] " + line
        case .remove(let offset, let line, _): return "- [line \(offset + 1)] " + line
        }
    }.joined(separator: "\n")
}

// MARK: - Action Execution Primitives

func postMouseClick(at pt: CGPoint) -> Bool {
    if cliOption("--window-id") != nil {
        guard let app = cliOption("--app"), let running = findRunningApp(named: app),
              inputWindowIsFocused(running.processIdentifier), let scope = focusedScope(running.processIdentifier),
              let b = getElementBounds(scope), pt.x >= b.x, pt.x <= b.x + b.width,
              pt.y >= b.y, pt.y <= b.y + b.height else { return false }
    }
    let src = CGEventSource(stateID: .hidSystemState)
    if let move = CGEvent(mouseEventSource: src, mouseType: .mouseMoved, mouseCursorPosition: pt, mouseButton: .left) {
        move.post(tap: .cghidEventTap)
        usleep(15000)
    }
    guard let down = CGEvent(mouseEventSource: src, mouseType: .leftMouseDown, mouseCursorPosition: pt, mouseButton: .left),
          let up = CGEvent(mouseEventSource: src, mouseType: .leftMouseUp, mouseCursorPosition: pt, mouseButton: .left) else {
        return false
    }

    down.post(tap: .cghidEventTap)
    usleep(25000) // 25ms
    up.post(tap: .cghidEventTap)
    invalidateOCRCache(for: nil)
    return true
}

func performClick(appPID: pid_t, elementIdx: Int) -> Bool {
    // 1. Try finding live element in accessibility tree
    if let (liveElem, actions) = findLiveElement(appPID: appPID, targetIndex: elementIdx) {
        // Priority 1: Native AXPress action
        if actions.contains(kAXPressAction as String) {
            let err = AXUIElementPerformAction(liveElem, kAXPressAction as CFString)
            if err == .success {
                invalidateOCRCache(for: nil)
                return true
            }
        }

        // Priority 2: Live bounds center click
        if NSRunningApplication(processIdentifier: appPID)?.isActive == true, let liveBounds = getElementBounds(liveElem) {
            let centerX = liveBounds.x + (liveBounds.width / 2.0)
            let centerY = liveBounds.y + (liveBounds.height / 2.0)
            return postMouseClick(at: CGPoint(x: centerX, y: centerY))
        }
    }


    return false
}

func performSetValue(appPID: pid_t, elementIndex: Int, value: String) -> Bool {
    guard let (liveElem, _) = findLiveElement(appPID: appPID, targetIndex: elementIndex) else {
        return false
    }
    let err = AXUIElementSetAttributeValue(liveElem, kAXValueAttribute as CFString, value as CFTypeRef)
    if err == .success {
        invalidateOCRCache(for: nil)
        return true
    }
    return false
}

func parseKeyAndModifiers(_ rawKey: String) -> (keyCode: CGKeyCode, modifiers: CGEventFlags)? {
    let lower = rawKey.lowercased().trimmingCharacters(in: .whitespacesAndNewlines)
    let parts = lower.components(separatedBy: CharacterSet(charactersIn: "+-"))
    var flags: CGEventFlags = []
    var mainKey: String = ""

    for (idx, part) in parts.enumerated() {
        let trimmed = part.trimmingCharacters(in: .whitespaces)
        if idx == parts.count - 1 {
            mainKey = trimmed
        } else {
            switch trimmed {
            case "cmd", "command", "super":
                flags.insert(.maskCommand)
            case "ctrl", "control":
                flags.insert(.maskControl)
            case "alt", "option", "opt":
                flags.insert(.maskAlternate)
            case "shift":
                flags.insert(.maskShift)
            default:
                return nil
            }
        }
    }

    let keyMap: [String: CGKeyCode] = [
        "return": 0x24, "enter": 0x24,
        "tab": 0x30,
        "space": 0x31,
        "delete": 0x33, "backspace": 0x33,
        "forwarddelete": 0x75,
        "escape": 0x35, "esc": 0x35,
        "up": 0x7E, "down": 0x7D, "left": 0x7B, "right": 0x7C,
        "pageup": 0x74, "pagedown": 0x79, "home": 0x73, "end": 0x77,
        "f1": 0x7A, "f2": 0x78, "f3": 0x63, "f4": 0x76,
        "f5": 0x60, "f6": 0x61, "f7": 0x62, "f8": 0x64,
        "f9": 0x65, "f10": 0x6D, "f11": 0x67, "f12": 0x6F,
        "a": 0x00, "s": 0x01, "d": 0x02, "f": 0x03, "h": 0x04, "g": 0x05, "z": 0x06,
        "x": 0x07, "c": 0x08, "v": 0x09, "b": 0x0B, "q": 0x0C, "w": 0x0D, "e": 0x0E,
        "r": 0x0F, "y": 0x10, "t": 0x11, "1": 0x12, "2": 0x13, "3": 0x14, "4": 0x15,
        "6": 0x16, "5": 0x17, "9": 0x19, "7": 0x1A, "8": 0x1C, "0": 0x1D, "o": 0x1F,
        "u": 0x20, "i": 0x22, "p": 0x23, "l": 0x25, "j": 0x26, "k": 0x28, "n": 0x2D, "m": 0x2E,
        "-": 0x1B, "=": 0x18, "[": 0x21, "]": 0x1E, "\\": 0x2A, ";": 0x29, "'": 0x27,
        ",": 0x2B, ".": 0x2F, "/": 0x2C, "`": 0x32
    ]

    guard let code = keyMap[mainKey] else {
        return nil
    }

    return (code, flags)
}

func performKeyPress(key: String, targetPID: pid_t? = nil, explicitModifiers: CGEventFlags = []) -> Bool {
    guard inputWindowIsFocused(targetPID) else { return false }
    guard let parsed = parseKeyAndModifiers(key) else {
        fputs("Error: Unknown or unsupported key '\(key)'\n", stderr)
        return false
    }

    var combinedModifiers = parsed.modifiers
    if !explicitModifiers.isEmpty {
        combinedModifiers.insert(explicitModifiers)
    }

    let src = CGEventSource(stateID: .hidSystemState)
    guard let down = CGEvent(keyboardEventSource: src, virtualKey: parsed.keyCode, keyDown: true),
          let up = CGEvent(keyboardEventSource: src, virtualKey: parsed.keyCode, keyDown: false) else {
        return false
    }

    if !combinedModifiers.isEmpty {
        down.flags = combinedModifiers
        up.flags = combinedModifiers
    }

    if let pid = targetPID, NSRunningApplication(processIdentifier: pid)?.isActive != true {
        down.postToPid(pid)
        usleep(15000)
        up.postToPid(pid)
    } else {
        down.post(tap: .cghidEventTap)
        usleep(15000)
        up.post(tap: .cghidEventTap)
    }
    invalidateOCRCache(for: nil)
    return true
}

func performPaste(text: String, targetPID: pid_t) -> Bool {
    let pb = NSPasteboard.general

    // 1. Backup existing pasteboard contents
    var backupItems: [(types: [NSPasteboard.PasteboardType], dataByType: [NSPasteboard.PasteboardType: Data])] = []
    if let pasteboardItems = pb.pasteboardItems {
        for item in pasteboardItems {
            var dataDict: [NSPasteboard.PasteboardType: Data] = [:]
            for type in item.types {
                if let d = item.data(forType: type) {
                    dataDict[type] = d
                }
            }
            if !dataDict.isEmpty {
                backupItems.append((types: item.types, dataByType: dataDict))
            }
        }
    }

    pb.clearContents()
    var ownedChangeCount = pb.changeCount
    defer {
        if pb.changeCount == ownedChangeCount {
            pb.clearContents()
            let items = backupItems.map { backup -> NSPasteboardItem in
                let item = NSPasteboardItem()
                for (type, data) in backup.dataByType { item.setData(data, forType: type) }
                return item
            }
            if !items.isEmpty { pb.writeObjects(items) }
        }
    }
    guard pb.setString(text, forType: .string) else { return false }
    ownedChangeCount = pb.changeCount
    let pressSuccess = performKeyPress(key: "v", targetPID: targetPID, explicitModifiers: .maskCommand)
    usleep(40000) // 40ms dispatch wait (down from 400ms)

    if pressSuccess {
        invalidateOCRCache(for: nil)
    }
    return pressSuccess
}

func performTypeText(_ text: String, targetPID: pid_t? = nil, pressReturn: Bool = false) -> Bool {
    let src = CGEventSource(stateID: .hidSystemState)

    for char in text {
        guard inputWindowIsFocused(targetPID) else { return false }
        if char == "\n" || char == "\r" {
            guard performKeyPress(key: "return", targetPID: targetPID) else { return false }
            usleep(25000) // 25ms
            continue
        }
        if char == "\t" {
            guard performKeyPress(key: "tab", targetPID: targetPID) else { return false }
            usleep(25000) // 25ms
            continue
        }

        let utf16Units = Array(String(char).utf16)
        guard let down = CGEvent(keyboardEventSource: src, virtualKey: 0, keyDown: true),
              let up = CGEvent(keyboardEventSource: src, virtualKey: 0, keyDown: false) else {
            return false
        }

        utf16Units.withUnsafeBufferPointer { ptr in
            down.keyboardSetUnicodeString(stringLength: ptr.count, unicodeString: ptr.baseAddress!)
            up.keyboardSetUnicodeString(stringLength: ptr.count, unicodeString: ptr.baseAddress!)
        }

        if let pid = targetPID, NSRunningApplication(processIdentifier: pid)?.isActive != true {
            down.postToPid(pid)
            usleep(2000)
            up.postToPid(pid)
        } else {
            down.post(tap: .cghidEventTap)
            usleep(2000)
            up.post(tap: .cghidEventTap)
        }
        usleep(3000)
    }

    if pressReturn {
        usleep(20000) // 20ms before pressing return
        guard performKeyPress(key: "return", targetPID: targetPID) else { return false }
    }

    invalidateOCRCache(for: nil)
    return true
}

func getFocusedUIElement(for pid: pid_t) -> AXUIElement? {
    let axApp = safeAXApplication(pid)
    var focused: AnyObject?
    guard AXUIElementCopyAttributeValue(axApp, kAXFocusedUIElementAttribute as CFString, &focused) == .success,
          let elem = focused else { return nil }
    return (elem as! AXUIElement)
}

func textMatchesTargetURL(_ text: String, targetURL: String) -> Bool {
    let cleanTarget = targetURL.trimmingCharacters(in: .whitespacesAndNewlines)
    let cleanText = text.trimmingCharacters(in: .whitespacesAndNewlines)
    if cleanText.localizedCaseInsensitiveContains(cleanTarget) {
        return true
    }
    let withoutScheme = cleanTarget.replacingOccurrences(of: "^https?://", with: "", options: .regularExpression)
    if !withoutScheme.isEmpty && cleanText.localizedCaseInsensitiveContains(withoutScheme) {
        return true
    }
    if let targetParsed = URL(string: cleanTarget), let host = targetParsed.host, !host.isEmpty {
        if cleanText.localizedCaseInsensitiveContains(host) {
            return true
        }
    }
    return false
}

func performNavigate(app: NSRunningApplication, url: String) -> Bool {
    let pid = app.processIdentifier
    if !app.isActive {
        app.activate()
        usleep(80000)
    }
    // Cmd + L focuses address bar
    guard performKeyPress(key: "l", targetPID: pid, explicitModifiers: .maskCommand) else {
        return false
    }

    // State-based wait: wait up to 300ms for focused element to be a text field / combo box / omnibox
    let focusDeadline = ProcessInfo.processInfo.systemUptime + 0.3
    var omnibox: AXUIElement? = nil
    while ProcessInfo.processInfo.systemUptime < focusDeadline {
        if let focused = getFocusedUIElement(for: pid) {
            var roleVal: AnyObject?
            if AXUIElementCopyAttributeValue(focused, kAXRoleAttribute as CFString, &roleVal) == .success,
               let role = roleVal as? String {
                if role == "AXTextField" || role == "AXComboBox" || role == "AXSearchField" {
                    omnibox = focused
                    break
                }
            }
        }
        usleep(20000)
    }

    // Try set_value first if omnibox found
    var verified = false
    if let box = omnibox {
        if AXUIElementSetAttributeValue(box, kAXValueAttribute as CFString, url as CFTypeRef) == .success {
            var checkVal: AnyObject?
            if AXUIElementCopyAttributeValue(box, kAXValueAttribute as CFString, &checkVal) == .success,
               let curStr = checkVal as? String, textMatchesTargetURL(curStr, targetURL: url) {
                verified = true
            }
        }
    }

    // If set_value didn't succeed or didn't verify, fall back to paste
    if !verified {
        guard performPaste(text: url, targetPID: pid) else { return false }
        // State-based check: verify target URL has actually appeared in the address bar
        let valueDeadline = ProcessInfo.processInfo.systemUptime + 0.35
        while ProcessInfo.processInfo.systemUptime < valueDeadline {
            let targetBox = omnibox ?? getFocusedUIElement(for: pid)
            if let box = targetBox {
                var val: AnyObject?
                if AXUIElementCopyAttributeValue(box, kAXValueAttribute as CFString, &val) == .success,
                   let str = val as? String, textMatchesTargetURL(str, targetURL: url) {
                    verified = true
                    break
                }
            }
            usleep(20000)
        }
    }

    // P1-6: Guard verified! Do NOT Return unless target URL is verified in address bar!
    guard verified else {
        fputs("performNavigate: Target URL '\(url)' was not verified in address bar before Return\n", stderr)
        return false
    }

    // Commit navigation with Return
    guard performKeyPress(key: "return", targetPID: pid) else {
        return false
    }
    invalidateOCRCache(for: nil)
    return true
}

func findChatInputElement(in element: AXUIElement, depth: Int = 0) -> AXUIElement? {
    if depth > 10 { return nil }
    var roleVal: AnyObject?
    if AXUIElementCopyAttributeValue(element, kAXRoleAttribute as CFString, &roleVal) == .success,
       let role = roleVal as? String {
        if role == "AXTextArea" || role == "AXTextField" {
            if let bounds = getElementBounds(element), bounds.width > 50, bounds.height > 15 {
                return element
            }
        }
    }

    var childrenVal: AnyObject?
    if AXUIElementCopyAttributeValue(element, kAXChildrenAttribute as CFString, &childrenVal) == .success,
       let children = childrenVal as? [AXUIElement] {
        for child in children.reversed() {
            if let found = findChatInputElement(in: child, depth: depth + 1) {
                return found
            }
        }
    }
    return nil
}

func performSendChat(app: NSRunningApplication, message: String, newChat: Bool = false) -> Bool {
    if !app.isActive {
        app.activate()
        usleep(120000)
    }

    if newChat {
        guard performKeyPress(key: "n", targetPID: app.processIdentifier, explicitModifiers: .maskCommand) else { return false }
        usleep(250000)
    }

    let appElement = safeAXApplication(app.processIdentifier)

    var targetInput: AXUIElement? = nil
    var focusedWindow: AXUIElement? = nil
    var focusedVal: AnyObject?
    if AXUIElementCopyAttributeValue(appElement, kAXFocusedWindowAttribute as CFString, &focusedVal) == .success,
       let win = focusedVal {
        focusedWindow = (win as! AXUIElement)
    }

    if let win = focusedWindow {
        targetInput = findChatInputElement(in: win)
    } else {
        targetInput = findChatInputElement(in: appElement)
    }

    if let inputElem = targetInput, let bounds = getElementBounds(inputElem) {
        let clickPt = CGPoint(x: bounds.x + bounds.width / 2.0, y: bounds.y + bounds.height / 2.0)
        guard postMouseClick(at: clickPt) else { return false }
        usleep(100000)
    } else {
        return false
    }

    guard performPaste(text: message, targetPID: app.processIdentifier) else {
        return false
    }
    usleep(150000)

    guard performKeyPress(key: "return", targetPID: app.processIdentifier) else {
        return false
    }

    return true
}

// All static validation completes before app lookup, activation, or input.
func validateBatch(_ actions: [ActionItem]) -> (Int, String)? {
    if actions.isEmpty || actions.count > 100 { return (0, "Batch must contain 1...100 actions") }
    var totalWait: UInt64 = 0
    for (i, item) in actions.enumerated() {
        let a = item.action.lowercased().trimmingCharacters(in: .whitespaces)
        func fail(_ message: String) -> (Int, String)? { return (i + 1, message) }
        if let ms = item.waitMs, ms > 10000 { return fail("waitMs must be <= 10000") }
        if let x = item.x, !x.isFinite { return fail("x must be finite") }
        if let y = item.y, !y.isFinite { return fail("y must be finite") }
        if let mods = item.modifiers {
            let allowed = Set(["cmd", "command", "super", "ctrl", "control", "alt", "opt", "option", "shift"])
            for m in mods {
                let clean = m.lowercased().trimmingCharacters(in: .whitespaces)
                if !allowed.contains(clean) {
                    return fail("Unknown modifier '\(m)'")
                }
            }
        }
        switch a {
        case "activate": break
        case "click", "set_value":
            guard let index = item.element, index > 0 else { return fail("Positive element required") }
            if a == "set_value" && item.value == nil { return fail("value required") }
        case "click_coord":
            if item.x == nil || item.y == nil { return fail("x and y required") }
        case "press_key":
            guard let key = item.key, parseKeyAndModifiers(key) != nil else { return fail("Unsupported or missing key") }
        case "navigate":
            guard let url = item.url, !url.isEmpty else { return fail("url required") }
        case "scroll":
            if let dir = item.direction?.lowercased() {
                guard ["up", "down", "left", "right"].contains(dir) else {
                    return fail("Invalid scroll direction '\(dir)', must be up, down, left, or right")
                }
            }
            if let amt = item.amount {
                guard (1...100).contains(amt) else {
                    return fail("Scroll amount must be between 1 and 100")
                }
            }
            if (item.x != nil && item.y == nil) || (item.x == nil && item.y != nil) {
                return fail("Both x and y must be provided for scroll coordinates")
            }
        case "type_text", "typetext", "type":
            if item.text == nil && item.value == nil { return fail("text required") }
        case "click_text", "clicktext":
            guard let text = item.text ?? item.value, !text.isEmpty else { return fail("text required") }
            if let occ = item.occurrence, occ < 1 { return fail("occurrence must be >= 1") }
            if let minConf = item.minConfidence, (minConf < 0.0 || minConf > 1.0) { return fail("minConfidence must be between 0.0 and 1.0") }
        case "paste", "wait_text", "waitfortext":
            guard let text = item.text ?? item.value, !text.isEmpty else { return fail("text required") }
        case "send_chat", "sendchat":
            guard let text = item.message ?? item.text ?? item.value, !text.isEmpty else { return fail("message required") }
        case "wait": break
        default: return fail("Unknown action '\(item.action)'")
        }
        if a == "wait" || a == "wait_text" || a == "waitfortext" {
            totalWait += UInt64(item.waitMs ?? (a == "wait" ? 100 : 3000))
            if totalWait > 10000 { return fail("Total requested wait exceeds 10000ms") }
        }
    }
    return nil
}

func actionMayMutateUI(_ action: String) -> Bool {
    let a = action.lowercased().trimmingCharacters(in: .whitespaces)
    switch a {
    case "click", "click_coord", "set_value", "press_key", "type_text", "typetext", "type",
         "paste", "click_text", "clicktext", "scroll", "navigate", "send_chat", "sendchat":
        return true
    default:
        return false
    }
}

// MARK: - Main CLI Router

func printUsage() {
    let usage = """
    Usage: mac-cua <command> [options]

    Commands:
      doctor [--prompt]                         Diagnose system permissions (Accessibility, Screen Recording)
      list-apps                                 List active GUI applications
      activate --app <name>                     Activate / bring application to foreground
      state --app <name> [--diff] [--no-img] [--compact] Inspect application accessibility tree & snapshot
      click --app <name> --element <index>      Click an accessibility element
      click-coord --x <x> --y <y>               Click specific desktop coordinates
      set-value --app <name> --element <idx> --value <text>  Directly set text attribute
      type-text [--app <name>] --text <str> [--press-return] Type text via Unicode injection (IME-safe, no clipboard)
      press-key --key <name>                    Press special key (Return, Tab, Escape, etc.)
      navigate --app <name> --url <url>         Atomically navigate browser address bar to URL
      send-chat --app <name> --message <text> [--new-chat] Atomically send message in chat app
      find-text --app <name> --text <query>     Locate text in window via Vision OCR
      click-text --app <name> --text <query>    Locate and click text in window via Vision OCR
      scroll --app <name> [--direction down|up|left|right] [--amount lines] Scroll window contents
      batch --app <name> --actions <json>       Execute a sequence of actions with strict fail-fast semantics
    """
    fputs(usage + "\n", stderr)
}

func main() {
    pruneStaleCacheFiles()
    pruneOldSessionDirs()
    let args = CommandLine.arguments
    guard args.count >= 2 else {
        printUsage()
        exit(1)
    }

    let command = args[1]

    switch command {
    case "list-windows":
        guard let name = cliOption("--app"), let app = findRunningApp(named: name) else {
            outputJSON(GenericResponse(success: false, error: "Application not found", code: "APP_NOT_FOUND")); exit(2)
        }
        let windows = (CGWindowListCopyWindowInfo([.optionAll, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]] ?? []).filter {
            ($0[kCGWindowOwnerPID as String] as? pid_t) == app.processIdentifier && ($0[kCGWindowLayer as String] as? Int) == 0
        }.map { ["windowId": $0[kCGWindowNumber as String] ?? 0, "title": $0[kCGWindowName as String] ?? "", "bounds": $0[kCGWindowBounds as String] ?? [:]] }
        if let data = try? JSONSerialization.data(withJSONObject: windows), let text = String(data: data, encoding: .utf8) { print(text) }
    case "list-apps":
        let runningApps = NSWorkspace.shared.runningApplications
            .filter { $0.activationPolicy == .regular }
            .map { app -> AppInfoItem in
                AppInfoItem(
                    pid: app.processIdentifier,
                    bundleId: app.bundleIdentifier,
                    name: app.localizedName ?? "Unknown",
                    isActive: app.isActive
                )
            }
        outputJSON(runningApps, pretty: true)

    case "doctor":
        var shouldPrompt = false
        for arg in args {
            if arg == "--prompt" {
                shouldPrompt = true
            }
        }

        let promptKey = kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String
        let isAXTrusted = AXIsProcessTrustedWithOptions([promptKey: shouldPrompt] as CFDictionary)

        var isScreenCaptureTrusted = false
        if #available(macOS 10.15, *) {
            isScreenCaptureTrusted = CGPreflightScreenCaptureAccess()
        } else {
            isScreenCaptureTrusted = true
        }

        var advice: [String] = []
        if !isAXTrusted {
            advice.append("Accessibility permission missing: Open System Settings -> Privacy & Security -> Accessibility and enable terminal/agent.")
        }
        if !isScreenCaptureTrusted {
            advice.append("Screen Recording permission missing: Open System Settings -> Privacy & Security -> Screen Recording and enable terminal/agent.")
        }
        if advice.isEmpty {
            advice.append("All permissions and engine components are healthy.")
        }

        let osVer = ProcessInfo.processInfo.operatingSystemVersionString
        #if arch(arm64)
        let archStr = "arm64"
        #else
        let archStr = "x86_64"
        #endif

        let doc = DoctorResponse(
            success: isAXTrusted && isScreenCaptureTrusted,
            accessibility: isAXTrusted,
            screenCapture: isScreenCaptureTrusted,
            osVersion: osVer,
            arch: archStr,
            binaryPath: CommandLine.arguments[0],
            advice: advice
        )
        outputJSON(doc, pretty: true)
        if !(isAXTrusted && isScreenCaptureTrusted) {
            exit(1)
        }

    case "activate":
        var target: String? = nil
        var i = 2
        while i < args.count {
            if args[i] == "--app", i + 1 < args.count {
                target = args[i + 1]
                i += 2
            } else {
                target = args[i]
                i += 1
            }
        }
        guard let appName = target else {
            fputs("Usage: mac-cua activate --app <name>\n", stderr)
            exit(1)
        }
        if let runningApp = findRunningApp(named: appName) {
            runningApp.activate()
            usleep(120000)
            let res = GenericResponse(success: true, action: "activated", pid: runningApp.processIdentifier)
            outputJSON(res)
        } else if launchApplicationByName(appName) {
            let res = GenericResponse(success: true, action: "launched")
            outputJSON(res)
        } else {
            let res = GenericResponse(success: false, error: "Could not launch or activate \(appName)")
            outputJSON(res)
            exit(2)
        }

    case "state":
        let stateStarted = ProcessInfo.processInfo.systemUptime
        var appName: String? = nil
        var useDiff = false
        var captureImg = true
        var compactMode = false

        var i = 2
        while i < args.count {
            if args[i] == "--app", i + 1 < args.count {
                appName = args[i + 1]
                i += 2
            } else if args[i] == "--diff" {
                useDiff = true
                i += 1
            } else if args[i] == "--no-img" {
                captureImg = false
                i += 1
            } else if args[i] == "--compact" {
                compactMode = true
                i += 1
            } else {
                i += 1
            }
        }

        guard let targetApp = appName, let runningApp = findRunningApp(named: targetApp) else {
            let res = GenericResponse(success: false, error: "Could not find running application matching '\(appName ?? "")'")
            outputJSON(res)
            exit(2)
        }

        let pid = runningApp.processIdentifier
        guard let focusedWindow = focusedScope(pid), let scopeBounds = getElementBounds(focusedWindow),
              let scopeID = scopedWindowID(pid, scopeBounds), let launch = runningApp.launchDate?.timeIntervalSince1970 else {
            outputJSON(GenericResponse(success: false, error: "No unambiguous window scope", code: "WINDOW_UNAVAILABLE"))
            exit(1)
        }
        var webAXStatus = "not_requested"
        let prepareStarted = ProcessInfo.processInfo.systemUptime
        if cliOption("--prepare-web") == "true" {
            let supported = ["com.microsoft.edgemac", "com.google.Chrome", "org.chromium.Chromium", "com.brave.Browser"]
            if !supported.contains(runningApp.bundleIdentifier ?? "") {
                webAXStatus = "unsupported_app"
            } else {
                if probeHasWebArea(element: focusedWindow) {
                    webAXStatus = "ready_initial"
                } else {
                    let axApp = safeAXApplication(pid)
                    let result = AXUIElementSetAttributeValue(axApp, "AXEnhancedUserInterface" as CFString, kCFBooleanTrue)
                    webAXStatus = result == .success ? "timeout" : "attribute_rejected"
                    if result == .success {
                        let deadline = ProcessInfo.processInfo.systemUptime + 1.0
                        repeat {
                            usleep(80000)
                            if probeHasWebArea(element: focusedWindow) {
                                webAXStatus = "ready_after_prepare"
                                break
                            }
                        } while ProcessInfo.processInfo.systemUptime < deadline
                    }
                }
            }
        }
        let prepareMs = (ProcessInfo.processInfo.systemUptime - prepareStarted) * 1000

        // Perform EXACTLY ONE full collection!
        let axStarted = ProcessInfo.processInfo.systemUptime
        let collector = TreeCollector()
        if let raw = cliOption("--max-nodes"), let customMax = Int(raw), customMax > 0 {
            collector.maxNodes = customMax
        }
        collector.compact = compactMode
        collector.collect(element: focusedWindow)
        let axFinished = ProcessInfo.processInfo.systemUptime
        let axCollectionMs = (axFinished - axStarted) * 1000

        if collector.hasWebArea && !webAXStatus.hasPrefix("ready") {
            webAXStatus = "ready_full_collection"
        }

        let snapshot = Snapshot(id: UUID().uuidString, session: sessionID, pid: pid, launchedAt: launch,
                                windowID: scopeID, bounds: scopeBounds, createdAt: Date().timeIntervalSince1970,
                                elements: collector.elements,
                                maxNodes: collector.maxNodes, maxDepth: 20, isTruncated: collector.isTruncated)
        do {
            try JSONEncoder().encode(snapshot).write(to: snapshotURL(snapshot.id)!, options: .atomic)
        } catch {
            outputJSON(GenericResponse(success: false, error: "Could not persist snapshot", code: "CACHE_ERROR"))
            exit(1)
        }

        let fullText = collector.textLines.joined(separator: "\n")
        var diffText: String? = nil

        let cacheFile = cacheURL(for: "\(pid):\(launch):\(scopeID):\(compactMode)", type: "tree")
        if useDiff {
            if let oldData = try? Data(contentsOf: cacheFile),
               let oldLines = try? JSONDecoder().decode([String].self, from: oldData) {
                diffText = computeDiff(oldLines: oldLines, newLines: collector.textLines)
            } else {
                diffText = "(initial baseline tree)"
            }
        }

        if let newData = try? JSONEncoder().encode(collector.textLines) {
            try? newData.write(to: cacheFile, options: .atomic)
        }

        let captureStarted = ProcessInfo.processInfo.systemUptime
        var screenshotUrl: String? = nil
        if captureImg {
            let captured = captureWindow(for: pid, targetBounds: scopeBounds)
            screenshotUrl = captured.1
        }
        let captureFinished = ProcessInfo.processInfo.systemUptime
        // Recheck the scope after capture: never pair a moved window with old AX geometry.
        guard let currentScope = focusedScope(pid), let currentBounds = getElementBounds(currentScope),
              scopedWindowID(pid, currentBounds) == scopeID, currentBounds == scopeBounds else {
            outputJSON(GenericResponse(success: false, error: "Window changed while observing", code: "STALE_SNAPSHOT"))
            exit(1)
        }
        let response = StateResponse(app: runningApp.localizedName ?? targetApp, pid: pid,
            windowId: scopeID, windowBounds: scopeBounds, text: fullText, diff: diffText,
            screenshotUrl: screenshotUrl, elementCount: collector.elements.count,
            elements: collector.elements, snapshotId: snapshot.id, sessionId: sessionID,
            timingsMs: ["axCollection": axCollectionMs,
                        "capture": (captureFinished - captureStarted) * 1000,
                        "webPreparation": prepareMs,
                        "stateTotal": (ProcessInfo.processInfo.systemUptime - stateStarted) * 1000],
            webAXStatus: webAXStatus,
            isTruncated: collector.isTruncated ? true : nil)
        outputJSON(response, pretty: true)

    case "click":
        guard let targetApp = cliOption("--app"), let raw = cliOption("--element"),
              let idx = Int(raw), idx > 0 else {
            outputJSON(GenericResponse(success: false, error: "--app and positive --element required", code: "INVALID_ARGUMENT"))
            exit(2)
        }
        guard let runningApp = findRunningApp(named: targetApp) else {
            outputJSON(GenericResponse(success: false, error: "Application not running", code: "APP_NOT_FOUND"))
            exit(2)
        }
        let success = performClick(appPID: runningApp.processIdentifier, elementIdx: idx)
        let res = GenericResponse(success: success, error: success ? nil : (actionError ?? "Click failed"), clickedIndex: idx, app: targetApp, code: success ? nil : (actionError != nil ? "STALE_SNAPSHOT" : "ACTION_FAILED"), status: success ? "dispatched" : "failed")
        outputJSON(res)
        if !success { exit(1) }

    case "click-coord":
        var targetX: Double? = nil
        var targetY: Double? = nil
        var i = 2
        while i < args.count {
            if args[i] == "--x", i + 1 < args.count {
                targetX = Double(args[i + 1])
                i += 2
            } else if args[i] == "--y", i + 1 < args.count {
                targetY = Double(args[i + 1])
                i += 2
            } else {
                i += 1
            }
        }

        guard let x = targetX, let y = targetY, x.isFinite, y.isFinite else {
            let res = GenericResponse(success: false, error: "--x and --y are required")
            outputJSON(res)
            exit(2)
        }

        let success = postMouseClick(at: CGPoint(x: x, y: y))
        let res = GenericResponse(success: success, x: x, y: y)
        outputJSON(res)
        if !success { exit(1) }

    case "set-value":
        var appName: String? = nil
        var elementIdx: Int? = nil
        var textValue: String? = nil

        var i = 2
        while i < args.count {
            if args[i] == "--app", i + 1 < args.count {
                appName = args[i + 1]
                i += 2
            } else if args[i] == "--element", i + 1 < args.count {
                elementIdx = Int(args[i + 1])
                i += 2
            } else if args[i] == "--value", i + 1 < args.count {
                textValue = args[i + 1]
                i += 2
            } else {
                i += 1
            }
        }

        guard let targetApp = appName, let idx = elementIdx, let val = textValue else {
            let res = GenericResponse(success: false, error: "--app, --element and --value are required")
            outputJSON(res)
            exit(2)
        }

        guard let runningApp = findRunningApp(named: targetApp) else {
            let res = GenericResponse(success: false, error: "App '\(targetApp)' not running")
            outputJSON(res)
            exit(2)
        }

        let success = performSetValue(appPID: runningApp.processIdentifier, elementIndex: idx, value: val)
        let res = GenericResponse(success: success, error: success ? nil : (actionError ?? "Set value failed"), element: idx, value: val, app: targetApp, code: success ? nil : (actionError != nil ? "STALE_SNAPSHOT" : "ACTION_FAILED"), status: success ? "dispatched" : "failed")
        outputJSON(res)
        if !success { exit(1) }

    case "press-key":
        var keyName = "return"
        if args.count >= 3 && args[2] == "--key" && args.count >= 4 {
            keyName = args[3]
        }
        let success = performKeyPress(key: keyName)
        let res = GenericResponse(success: success, error: success ? nil : "Unknown key '\(keyName)'", key: keyName)
        outputJSON(res)
        if !success { exit(1) }

    case "type-text", "typetext":
        var appName: String? = nil
        var textContent: String? = nil
        var pressReturn = false
        var i = 2
        while i < args.count {
            if args[i] == "--app", i + 1 < args.count {
                appName = args[i + 1]
                i += 2
            } else if (args[i] == "--text" || args[i] == "--value"), i + 1 < args.count {
                textContent = args[i + 1]
                i += 2
            } else if args[i] == "--press-return" || args[i] == "--return" {
                pressReturn = true
                i += 1
            } else {
                i += 1
            }
        }
        guard let textToType = textContent else {
            let res = GenericResponse(success: false, error: "--text (or --value) is required")
            outputJSON(res)
            exit(2)
        }

        var targetPID: pid_t? = nil
        if let target = appName {
            guard let runningApp = findRunningApp(named: target) else {
                let res = GenericResponse(success: false, error: "App '\(target)' not running")
                outputJSON(res)
                exit(2)
            }
            if !runningApp.isActive {
                runningApp.activate()
                usleep(120000)
            }
            targetPID = runningApp.processIdentifier
        }

        let success = performTypeText(textToType, targetPID: targetPID, pressReturn: pressReturn)
        let res = GenericResponse(success: success, app: appName, text: textToType)
        outputJSON(res)
        if !success { exit(1) }

    case "navigate":
        var appName: String? = nil
        var targetUrl: String? = nil
        var i = 2
        while i < args.count {
            if args[i] == "--app", i + 1 < args.count {
                appName = args[i + 1]
                i += 2
            } else if args[i] == "--url", i + 1 < args.count {
                targetUrl = args[i + 1]
                i += 2
            } else {
                i += 1
            }
        }
        guard let target = appName, let url = targetUrl else {
            let res = GenericResponse(success: false, error: "--app and --url are required")
            outputJSON(res)
            exit(2)
        }
        guard let runningApp = findRunningApp(named: target) else {
            let res = GenericResponse(success: false, error: "App '\(target)' not running")
            outputJSON(res)
            exit(2)
        }
        let success = performNavigate(app: runningApp, url: url)
        let res = GenericResponse(success: success, app: target, navigatedTo: url, status: success ? "dispatched" : "failed")
        outputJSON(res)
        if !success { exit(1) }

    case "send-chat":
        var appName: String? = nil
        var chatMsg: String? = nil
        var newChat = false
        var i = 2
        while i < args.count {
            if args[i] == "--app", i + 1 < args.count {
                appName = args[i + 1]
                i += 2
            } else if (args[i] == "--message" || args[i] == "--msg" || args[i] == "--text"), i + 1 < args.count {
                chatMsg = args[i + 1]
                i += 2
            } else if args[i] == "--new-chat" || args[i] == "--new" {
                newChat = true
                i += 1
            } else {
                i += 1
            }
        }
        guard let target = appName, let msg = chatMsg else {
            let res = GenericResponse(success: false, error: "--app and --message are required")
            outputJSON(res)
            exit(2)
        }
        guard let runningApp = findRunningApp(named: target) else {
            let res = GenericResponse(success: false, error: "App '\(target)' not running")
            outputJSON(res)
            exit(2)
        }
        let success = performSendChat(app: runningApp, message: msg, newChat: newChat)
        let res = GenericResponse(success: success, action: "send-chat", app: target, message: msg, status: success ? "dispatched" : "failed")
        outputJSON(res)
        if !success { exit(1) }

    case "find-text":
        var appName: String? = nil
        var queryText: String? = nil
        var exact = false
        var minConf: Float = 0.0
        var i = 2
        while i < args.count {
            if args[i] == "--app", i + 1 < args.count {
                appName = args[i + 1]
                i += 2
            } else if args[i] == "--text", i + 1 < args.count {
                queryText = args[i + 1]
                i += 2
            } else if args[i] == "--exact" {
                exact = true
                i += 1
            } else if args[i] == "--min-confidence", i + 1 < args.count {
                minConf = Float(args[i + 1]) ?? 0.0
                i += 2
            } else {
                i += 1
            }
        }
        guard let target = appName, let query = queryText else {
            let res = GenericResponse(success: false, error: "--app and --text are required")
            outputJSON(res)
            exit(2)
        }
        guard let runningApp = findRunningApp(named: target) else {
            let res = GenericResponse(success: false, error: "App '\(target)' not running")
            outputJSON(res)
            exit(2)
        }
        let matches = findMatchesInWindow(appPID: runningApp.processIdentifier, query: query, exact: exact, minConfidence: minConf)
        if !matches.isEmpty {
            let best = matches.first!
            let res = GenericResponse(success: true, app: target, foundText: best.text,
                                      desktopX: best.desktopX, desktopY: best.desktopY,
                                      confidence: best.confidence, bounds: best.bounds,
                                      matchCount: matches.count, matches: matches)
            outputJSON(res)
        } else {
            let res = GenericResponse(success: false, error: "Text '\(query)' not found in window of '\(target)'", app: target, matchCount: 0, matches: [])
            outputJSON(res)
            exit(1)
        }

    case "click-text":
        var appName: String? = nil
        var queryText: String? = nil
        var exact = false
        var occurrence: Int? = nil
        var minConf: Float = 0.0
        var i = 2
        while i < args.count {
            if args[i] == "--app", i + 1 < args.count {
                appName = args[i + 1]
                i += 2
            } else if args[i] == "--text", i + 1 < args.count {
                queryText = args[i + 1]
                i += 2
            } else if args[i] == "--exact" {
                exact = true
                i += 1
            } else if args[i] == "--occurrence", i + 1 < args.count {
                occurrence = Int(args[i + 1])
                i += 2
            } else if args[i] == "--min-confidence", i + 1 < args.count {
                minConf = Float(args[i + 1]) ?? 0.0
                i += 2
            } else {
                i += 1
            }
        }
        guard let target = appName, let query = queryText else {
            let res = GenericResponse(success: false, error: "--app and --text are required")
            outputJSON(res)
            exit(2)
        }
        guard let runningApp = findRunningApp(named: target) else {
            let res = GenericResponse(success: false, error: "App '\(target)' not running")
            outputJSON(res)
            exit(2)
        }
        if !runningApp.isActive {
            runningApp.activate()
            usleep(80000)
        }
        do {
            let targetMatch = try resolveOCRTarget(
                appPID: runningApp.processIdentifier,
                query: query,
                exact: exact,
                occurrence: occurrence,
                minConfidence: minConf
            )
            let ok = postMouseClick(at: CGPoint(x: targetMatch.desktopX, y: targetMatch.desktopY))
            invalidateOCRCache(for: nil)
            var res = GenericResponse(success: ok, action: "click-text", app: target, status: ok ? "dispatched" : "failed")
            res.foundText = targetMatch.text
            res.desktopX = targetMatch.desktopX
            res.desktopY = targetMatch.desktopY
            res.confidence = targetMatch.confidence
            res.bounds = targetMatch.bounds
            outputJSON(res)
            if !ok { exit(1) }
        } catch OCRError.notFound(let q) {
            let res = GenericResponse(success: false, error: "Text '\(q)' not found in window of '\(target)'", app: target, code: "TEXT_NOT_FOUND")
            outputJSON(res)
            exit(1)
        } catch OCRError.outOfBounds(let occ, let count) {
            let res = GenericResponse(success: false, error: "Occurrence \(occ) out of bounds (\(count) matches found for '\(query)')", app: target, code: "OUT_OF_BOUNDS", matchCount: count)
            outputJSON(res)
            exit(1)
        } catch OCRError.ambiguous(let q, let count, let ms) {
            let res = GenericResponse(success: false, error: "Ambiguous text '\(q)': found \(count) matches. Specify --occurrence <1..N> to disambiguate.", app: target, code: "AMBIGUOUS_TEXT", matchCount: count, matches: ms)
            outputJSON(res)
            exit(1)
        } catch {
            let res = GenericResponse(success: false, error: "OCR error: \(error)", app: target, code: "ACTION_FAILED")
            outputJSON(res)
            exit(1)
        }

    case "batch":
        var appName: String? = nil
        var actionsJson: String? = nil
        var i = 2
        while i < args.count {
            if args[i] == "--app", i + 1 < args.count {
                appName = args[i + 1]
                i += 2
            } else if args[i] == "--actions", i + 1 < args.count {
                actionsJson = args[i + 1]
                i += 2
            } else {
                i += 1
            }
        }
        if actionsJson == nil {
            let input = FileHandle.standardInput.readDataToEndOfFile()
            actionsJson = String(data: input, encoding: .utf8)
        }
        guard let target = appName, let rawJson = actionsJson, let jsonData = rawJson.data(using: .utf8) else {
            let res = GenericResponse(success: false, error: "--app and --actions (or stdin) are required")
            outputJSON(res)
            exit(2)
        }
        let allowedKeys: Set<String> = ["action", "element", "value", "text", "message", "key", "url", "x", "y", "waitMs", "exact", "newChat", "pressReturn", "modifiers", "direction", "amount", "occurrence", "minConfidence"]
        guard let objects = (try? JSONSerialization.jsonObject(with: jsonData)) as? [[String: Any]],
              objects.allSatisfy({ Set($0.keys).isSubset(of: allowedKeys) }) else {
            outputJSON(GenericResponse(success: false, error: "Invalid action array or unknown action parameter", executed: 0, code: "INVALID_ARGUMENT", status: "rejected"))
            exit(2)
        }
        guard let actionList = try? JSONDecoder().decode([ActionItem].self, from: jsonData) else {
            let res = GenericResponse(success: false, error: "Failed to parse actions JSON array", executed: 0, code: "INVALID_ARGUMENT", status: "rejected")
            outputJSON(res)
            exit(2)
        }

        if let (index, message) = validateBatch(actionList) {
            outputJSON(GenericResponse(success: false, error: message, executed: 0, failedIndex: index, code: "INVALID_ARGUMENT", status: "rejected"))
            exit(2)
        }
        if actionList.contains(where: { ["click", "set_value"].contains($0.action.lowercased().trimmingCharacters(in: .whitespaces)) }) && cliOption("--snapshot") == nil {
            outputJSON(GenericResponse(success: false, error: "--snapshot is required for indexed actions", executed: 0, code: "STALE_SNAPSHOT"))
            exit(2)
        }
        guard let runningApp = findRunningApp(named: target) else {
            let res = GenericResponse(success: false, error: "App '\(target)' not running")
            outputJSON(res)
            exit(2)
        }
        var executedCount = 0
        var failureDetails: (index: Int, error: String)? = nil

        for (idx, item) in actionList.enumerated() {
            let stepNum = idx + 1
            let actionType = item.action.lowercased().trimmingCharacters(in: .whitespaces)

            if cliOption("--window-id") != nil && !["activate", "wait", "wait_text"].contains(actionType) && !inputWindowIsFocused(runningApp.processIdentifier) {
                failureDetails = (stepNum, "WINDOW_FOCUS_CHANGED: focus the selected window before continuing")
                break
            }
            switch actionType {
            case "activate":
                if !activateSelectedWindow(runningApp) {
                    failureDetails = (stepNum, "WINDOW_FOCUS_CHANGED: could not focus selected window")
                }

            case "click":
                guard let elemIdx = item.element else {
                    failureDetails = (stepNum, "Missing required parameter 'element' for action 'click'")
                    break
                }
                let ok = performClick(appPID: runningApp.processIdentifier, elementIdx: elemIdx)
                if !ok {
                    failureDetails = (stepNum, actionError ?? "Failed to click element index \(elemIdx)")
                    break
                }

            case "click_coord":
                guard let x = item.x, let y = item.y else {
                    failureDetails = (stepNum, "Missing required parameters 'x' and 'y' for action 'click_coord'")
                    break
                }
                let ok = postMouseClick(at: CGPoint(x: x, y: y))
                if !ok {
                    failureDetails = (stepNum, "Failed to post click at coordinates (\(x), \(y))")
                    break
                }

            case "set_value":
                guard let elemIdx = item.element, let val = item.value else {
                    failureDetails = (stepNum, "Missing required parameters 'element' and/or 'value' for action 'set_value'")
                    break
                }
                let ok = performSetValue(appPID: runningApp.processIdentifier, elementIndex: elemIdx, value: val)
                if !ok {
                    failureDetails = (stepNum, actionError ?? "Failed to set value on element index \(elemIdx)")
                    break
                }

            case "press_key":
                guard let key = item.key, !key.isEmpty else {
                    failureDetails = (stepNum, "Missing required parameter 'key' for action 'press_key'")
                    break
                }
                var modFlags: CGEventFlags = []
                if let mods = item.modifiers {
                    for m in mods {
                        switch m.lowercased() {
                        case "cmd", "command": modFlags.insert(.maskCommand)
                        case "ctrl", "control": modFlags.insert(.maskControl)
                        case "alt", "option", "opt": modFlags.insert(.maskAlternate)
                        case "shift": modFlags.insert(.maskShift)
                        default: break
                        }
                    }
                }
                let ok = performKeyPress(key: key, targetPID: runningApp.processIdentifier, explicitModifiers: modFlags)
                if !ok {
                    failureDetails = (stepNum, "Failed to press key '\(key)': unknown key or event error")
                    break
                }

            case "scroll":
                let direction = item.direction?.lowercased() ?? "down"
                guard ["up", "down", "left", "right"].contains(direction) else {
                    failureDetails = (stepNum, "Invalid scroll direction '\(direction)'")
                    break
                }
                let amount = item.amount ?? 5
                guard (1...100).contains(amount) else {
                    failureDetails = (stepNum, "Scroll amount must be between 1 and 100")
                    break
                }
                guard let scope = focusedScope(runningApp.processIdentifier),
                      let bounds = getElementBounds(scope) else {
                    failureDetails = (stepNum, "No window scope found for '\(target)'")
                    break
                }
                if cliOption("--window-id") != nil {
                    guard inputWindowIsFocused(runningApp.processIdentifier) else {
                        failureDetails = (stepNum, "Target window is not focused")
                        break
                    }
                }
                if !runningApp.isActive {
                    runningApp.activate()
                    usleep(60000)
                }
                let bX = bounds.x
                let bY = bounds.y
                let bW = bounds.width
                let bH = bounds.height
                if let tx = item.x, let ty = item.y {
                    guard tx >= bX && tx <= (bX + bW) && ty >= bY && ty <= (bY + bH) else {
                        failureDetails = (stepNum, "Scroll coordinates (\(tx), \(ty)) outside window bounds (\(bX), \(bY), \(bW), \(bH))")
                        break
                    }
                }
                let scrollPt = CGPoint(x: item.x ?? (bX + bW / 2.0), y: item.y ?? (bY + bH / 2.0))
                var wheel1: Int32 = 0
                var wheel2: Int32 = 0
                let amt = Int32(amount)
                switch direction {
                case "up": wheel1 = amt
                case "down": wheel1 = -amt
                case "left": wheel2 = amt
                case "right": wheel2 = -amt
                default: wheel1 = -amt
                }
                guard let scrollEvent = CGEvent(scrollWheelEvent2Source: nil, units: .line, wheelCount: wheel2 != 0 ? 2 : 1, wheel1: wheel1, wheel2: wheel2, wheel3: 0) else {
                    failureDetails = (stepNum, "Failed to create scroll event")
                    break
                }
                scrollEvent.location = scrollPt
                scrollEvent.post(tap: .cghidEventTap)
                usleep(30000)
                invalidateOCRCache(for: nil)

            case "navigate":
                guard let url = item.url, !url.isEmpty else {
                    failureDetails = (stepNum, "Missing required parameter 'url' for action 'navigate'")
                    break
                }
                let ok = performNavigate(app: runningApp, url: url)
                if !ok {
                    failureDetails = (stepNum, "Failed to navigate to url '\(url)'")
                    break
                }

            case "paste":
                let content = item.text ?? item.value
                guard let pasteText = content, !pasteText.isEmpty else {
                    failureDetails = (stepNum, "Missing required text content for action 'paste'")
                    break
                }
                let ok = performPaste(text: pasteText, targetPID: runningApp.processIdentifier)
                if !ok {
                    failureDetails = (stepNum, "Failed to paste text")
                    break
                }

            case "type_text", "typetext", "type":
                let content = item.text ?? item.value
                guard let textToType = content else {
                    failureDetails = (stepNum, "Missing required parameter 'text' or 'value' for action 'type_text'")
                    break
                }
                if !runningApp.isActive {
                    runningApp.activate()
                    usleep(120000)
                }
                let shouldPressReturn = item.pressReturn ?? false
                let ok = performTypeText(textToType, targetPID: runningApp.processIdentifier, pressReturn: shouldPressReturn)
                if !ok {
                    failureDetails = (stepNum, "Failed to type text")
                    break
                }

            case "click_text", "clicktext":
                let query = item.text ?? item.value
                guard let textQuery = query, !textQuery.isEmpty else {
                    failureDetails = (stepNum, "Missing required parameter 'text' for action 'click_text'")
                    break
                }
                if !runningApp.isActive {
                    runningApp.activate()
                    usleep(120000)
                }
                let exact = item.exact ?? false
                let occ = item.occurrence
                let minConf = item.minConfidence ?? 0.0
                do {
                    let match = try resolveOCRTarget(
                        appPID: runningApp.processIdentifier,
                        query: textQuery,
                        exact: exact,
                        occurrence: occ,
                        minConfidence: minConf
                    )
                    let ok = postMouseClick(at: CGPoint(x: match.desktopX, y: match.desktopY))
                    if !ok {
                        failureDetails = (stepNum, "Failed to post click at text '\(textQuery)' coordinates (\(match.desktopX), \(match.desktopY))")
                        break
                    }
                } catch OCRError.notFound(let q) {
                    failureDetails = (stepNum, "Text '\(q)' not found in window of '\(target)'")
                    break
                } catch OCRError.outOfBounds(let o, let count) {
                    failureDetails = (stepNum, "Occurrence \(o) out of bounds (\(count) matches found for '\(textQuery)')")
                    break
                } catch OCRError.ambiguous(let q, let count, _) {
                    failureDetails = (stepNum, "AMBIGUOUS_TEXT: found \(count) matches for '\(q)'. Specify occurrence <1..N> to disambiguate.")
                    break
                } catch {
                    failureDetails = (stepNum, "OCR error: \(error)")
                    break
                }

            case "wait_text", "waitfortext":
                let query = item.text ?? item.value
                guard let textQuery = query, !textQuery.isEmpty else {
                    failureDetails = (stepNum, "Missing required parameter 'text' for action 'wait_text'")
                    break
                }
                let totalWaitMs = item.waitMs ?? 3000
                let stepIntervalMs: UInt32 = 250
                let deadline = ProcessInfo.processInfo.systemUptime + Double(totalWaitMs) / 1000
                var found = false
                let exact = item.exact ?? false
                repeat {
                    if let _ = findTextInWindow(appPID: runningApp.processIdentifier, query: textQuery, exact: exact) {
                        found = true
                        break
                    }
                    let remaining = deadline - ProcessInfo.processInfo.systemUptime
                    if remaining > 0 { usleep(UInt32(min(remaining, Double(stepIntervalMs) / 1000) * 1_000_000)) }
                } while ProcessInfo.processInfo.systemUptime < deadline
                if !found {
                    failureDetails = (stepNum, "Timed out waiting for text '\(textQuery)' after \(totalWaitMs)ms in '\(target)'")
                    break
                }

            case "send_chat", "sendchat":
                let content = item.message ?? item.text ?? item.value
                guard let msg = content, !msg.isEmpty else {
                    failureDetails = (stepNum, "Missing required parameter 'message' or 'text' for action 'send_chat'")
                    break
                }
                let isNew = item.newChat ?? false
                let ok = performSendChat(app: runningApp, message: msg, newChat: isNew)
                if !ok {
                    failureDetails = (stepNum, "Failed to send chat message in '\(target)'")
                    break
                }

            case "wait":
                let ms = item.waitMs ?? 100
                usleep(ms * 1000)

            default:
                failureDetails = (stepNum, "Unknown action '\(item.action)'")
                break
            }

            if let _ = failureDetails {
                break
            }
            executedCount += 1
            if actionMayMutateUI(item.action) {
                invalidateOCRCache(for: nil)
            }
        }

        if let fail = failureDetails {
            let code: String
            if fail.error.hasPrefix("STALE_SNAPSHOT") {
                code = "STALE_SNAPSHOT"
            } else if fail.error.hasPrefix("AMBIGUOUS_TEXT") {
                code = "AMBIGUOUS_TEXT"
            } else {
                code = "ACTION_FAILED"
            }
            let res = GenericResponse(
                success: false,
                error: fail.error,
                app: target,
                executed: executedCount,
                failedIndex: fail.index,
                code: code,
                status: "failed"
            )
            outputJSON(res)
            exit(1)
        } else {
            let res = GenericResponse(
                success: true,
                app: target,
                executed: executedCount,
                status: "dispatched"
            )
            outputJSON(res)
        }

    case "scroll":
        var appName: String? = nil
        var direction = "down"
        var amount: Int = 5
        var targetX: Double? = nil
        var targetY: Double? = nil
        var i = 2
        while i < args.count {
            if args[i] == "--app", i + 1 < args.count {
                appName = args[i + 1]
                i += 2
            } else if args[i] == "--direction", i + 1 < args.count {
                direction = args[i + 1].lowercased()
                i += 2
            } else if args[i] == "--amount", i + 1 < args.count {
                if let parsed = Int(args[i + 1]) {
                    amount = parsed
                } else {
                    let res = GenericResponse(success: false, error: "Invalid amount integer: '\(args[i + 1])'", code: "INVALID_ARGUMENT")
                    outputJSON(res)
                    exit(2)
                }
                i += 2
            } else if args[i] == "--x", i + 1 < args.count {
                targetX = Double(args[i + 1])
                i += 2
            } else if args[i] == "--y", i + 1 < args.count {
                targetY = Double(args[i + 1])
                i += 2
            } else {
                i += 1
            }
        }
        guard let target = appName, let runningApp = findRunningApp(named: target) else {
            let res = GenericResponse(success: false, error: "--app is required and must be running")
            outputJSON(res)
            exit(2)
        }
        guard ["up", "down", "left", "right"].contains(direction) else {
            let res = GenericResponse(success: false, error: "Invalid scroll direction '\(direction)', must be up, down, left, or right", code: "INVALID_ARGUMENT")
            outputJSON(res)
            exit(2)
        }
        guard (1...100).contains(amount) else {
            let res = GenericResponse(success: false, error: "Scroll amount must be between 1 and 100, got \(amount)", code: "INVALID_ARGUMENT")
            outputJSON(res)
            exit(2)
        }
        let pid = runningApp.processIdentifier
        guard let scope = focusedScope(pid), let bounds = getElementBounds(scope) else {
            let res = GenericResponse(success: false, error: "No window bounds found for '\(target)'", code: "WINDOW_UNAVAILABLE")
            outputJSON(res)
            exit(1)
        }

        if cliOption("--window-id") != nil {
            guard inputWindowIsFocused(pid) else {
                let res = GenericResponse(success: false, error: "Target window is not focused", code: "WINDOW_FOCUS_LOST")
                outputJSON(res)
                exit(1)
            }
        }

        if !runningApp.isActive {
            runningApp.activate()
            usleep(60000)
        }

        if let tx = targetX, let ty = targetY {
            guard tx >= bounds.x && tx <= (bounds.x + bounds.width) &&
                  ty >= bounds.y && ty <= (bounds.y + bounds.height) else {
                let res = GenericResponse(
                    success: false,
                    error: "Scroll coordinates (\(tx), \(ty)) outside window bounds [\(bounds.x), \(bounds.y), \(bounds.width), \(bounds.height)]",
                    code: "COORDINATES_OUT_OF_BOUNDS"
                )
                outputJSON(res)
                exit(1)
            }
        }

        let scrollPt = CGPoint(
            x: targetX ?? (bounds.x + bounds.width / 2.0),
            y: targetY ?? (bounds.y + bounds.height / 2.0)
        )

        var wheel1: Int32 = 0
        var wheel2: Int32 = 0
        let amt = Int32(amount)
        switch direction {
        case "up": wheel1 = amt
        case "down": wheel1 = -amt
        case "left": wheel2 = amt
        case "right": wheel2 = -amt
        default: wheel1 = -amt
        }

        guard let scrollEvent = CGEvent(scrollWheelEvent2Source: nil, units: .line, wheelCount: wheel2 != 0 ? 2 : 1, wheel1: wheel1, wheel2: wheel2, wheel3: 0) else {
            let res = GenericResponse(success: false, error: "Failed to construct scroll event", code: "ACTION_FAILED")
            outputJSON(res)
            exit(1)
        }
        scrollEvent.location = scrollPt
        scrollEvent.post(tap: .cghidEventTap)
        usleep(30000)

        invalidateOCRCache(for: nil)
        var res = GenericResponse(success: true, action: "scroll", app: target, status: "dispatched")
        res.direction = direction
        res.amount = Int(amt)
        res.x = Double(scrollPt.x)
        res.y = Double(scrollPt.y)
        outputJSON(res)

    default:
        printUsage()
        exit(1)
    }
}

main()
