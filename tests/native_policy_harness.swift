if CommandLine.arguments.count > 1 { main() }
let bounds = ElementBounds(x: 10, y: 20, width: 500, height: 400)
let element = ParsedElement(index: 1, role: "AXButton", title: "Submit", value: nil,
                            desc: nil, actions: ["AXPress"], bounds: bounds)
let snap = Snapshot(id: UUID().uuidString, session: sessionID, pid: 123, launchedAt: 1,
                    windowID: 7, bounds: bounds, createdAt: 100, elements: [element])
func matches(pid: pid_t = 123, launch: Double = 1, window: CGWindowID = 7,
             box: ElementBounds = bounds, items: [ParsedElement] = [element], now: Double = 101) -> Bool {
    snapshotMatches(snap, pid: pid, launchedAt: launch, windowID: window, bounds: box, elements: items, now: now)
}
assert(matches())
assert(!matches(pid: 124))
assert(!matches(launch: 2))
assert(!matches(window: 8))
assert(!matches(box: ElementBounds(x: 30, y: 20, width: 500, height: 400)))
assert(!matches(items: []))
assert(!matches(items: [element, element]))
assert(matches(now: 161))
assert(!matches(now: 221))
assert(!matches(now: 99))
let changed = ParsedElement(index: 1, role: "AXButton", title: "Delete", value: nil,
                            desc: nil, actions: ["AXPress"], bounds: bounds)
assert(!matches(items: [changed])) // Same role, different target must not pass.
let unrelated = ParsedElement(index: 2, role: "AXLink", title: "Countdown 10", value: nil,
                             desc: nil, actions: ["AXPress"], bounds: nil)
assert(matches(items: [element, unrelated]))
var renumbered = element
renumbered = ParsedElement(index: 2, role: element.role, title: element.title, value: nil,
                          desc: nil, actions: element.actions, bounds: element.bounds)
assert(resolveSnapshotTarget(snap, pid: 123, launchedAt: 1, windowID: 7, bounds: bounds,
                             elements: [unrelated, renumbered], targetIndex: 1, now: 101) == 1)
assert(resolveSnapshotTarget(snap, pid: 123, launchedAt: 1, windowID: 7, bounds: bounds,
                             elements: [element], targetIndex: 99, now: 101) == nil)
let input = ParsedElement(index: 1, role: "AXComboBox", title: "Search", value: "", desc: nil,
                          actions: [], bounds: bounds, identifier: "search-box")
let inputSnap = Snapshot(id: UUID().uuidString, session: sessionID, pid: 123, launchedAt: 1,
                         windowID: 7, bounds: bounds, createdAt: 100, elements: [input])
var typed = ParsedElement(index: 3, role: "AXComboBox", title: "Search", value: "pixel 8", desc: nil,
                          actions: [], bounds: ElementBounds(x: 25, y: 25, width: 500, height: 400), identifier: "search-box")
assert(snapshotMatches(inputSnap, pid: 123, launchedAt: 1, windowID: 7, bounds: bounds,
                       elements: [typed], targetIndex: 1, now: 101))
typed.identifier = "another-search-box"
assert(!snapshotMatches(inputSnap, pid: 123, launchedAt: 1, windowID: 7, bounds: bounds,
                        elements: [typed], targetIndex: 1, now: 101))
assert(snapshotURL("../../escape") == nil)
assert(cacheURL(for: "访达", type: "tree") != cacheURL(for: "音乐", type: "tree"))
func validate(_ json: String) -> (Int, String)? {
    validateBatch(try! JSONDecoder().decode([ActionItem].self, from: Data(json.utf8)))
}
assert(validate(#"[{"action":"wait","waitMs":0},{"action":"unknown"}]"#)?.0 == 2)
assert(validate(#"[{"action":"activate"},{"action":"click"}]"#)?.0 == 2)
assert(validate(#"[{"action":"wait","waitMs":4294967295}]"#)?.0 == 1)
assert(validate(#"[{"action":"wait","waitMs":6000},{"action":"wait","waitMs":6000}]"#)?.0 == 2)
assert(validate(#"[{"action":"press_key","key":"not_a_key"}]"#)?.0 == 1)
assert(validate(#"[{"action":"wait","waitMs":0}]"#) == nil)
assert(validate("[]") != nil)
assert(computeDiff(oldLines: ["A", "B"], newLines: ["B", "A"]) != "(no visible UI changes)")
assert(computeDiff(oldLines: ["A", "A"], newLines: ["A"]) != "(no visible UI changes)")
// MARK: - Phase 3.1: URL Verification Tests
// 1. Same host, different path -> MUST BE FALSE
assert(!textMatchesTargetURL("https://example.com/home", targetURL: "https://example.com/checkout/pay"))
assert(!textMatchesTargetURL("example.com/home", targetURL: "https://example.com/checkout/pay"))
assert(!textMatchesTargetURL("https://example.com/", targetURL: "https://example.com/checkout/pay"))

// 2. Same host, same path -> TRUE
assert(textMatchesTargetURL("https://example.com/checkout/pay", targetURL: "https://example.com/checkout/pay"))
assert(textMatchesTargetURL("example.com/checkout/pay", targetURL: "https://example.com/checkout/pay"))
assert(textMatchesTargetURL("example.com/checkout/pay/", targetURL: "https://example.com/checkout/pay"))
assert(textMatchesTargetURL("http://example.com/checkout/pay", targetURL: "https://example.com/checkout/pay"))

// 3. Same host, query parameters match vs mismatch
assert(textMatchesTargetURL("https://s.taobao.com/search?q=Pixel+8", targetURL: "https://s.taobao.com/search?q=Pixel+8"))
assert(textMatchesTargetURL("s.taobao.com/search?q=Pixel+8", targetURL: "https://s.taobao.com/search?q=Pixel+8"))
assert(!textMatchesTargetURL("s.taobao.com", targetURL: "https://s.taobao.com/search?q=Pixel+8"))
assert(!textMatchesTargetURL("https://s.taobao.com/search?q=iPhone", targetURL: "https://s.taobao.com/search?q=Pixel+8"))

// 4. Root host match vs root with unrequested path
assert(textMatchesTargetURL("https://taobao.com", targetURL: "https://taobao.com"))
assert(textMatchesTargetURL("taobao.com/", targetURL: "https://taobao.com"))
assert(!textMatchesTargetURL("https://taobao.com/item/123", targetURL: "https://taobao.com"))

// MARK: - Phase 3.1: OCR Resolution & Bounds Tests
let b1 = ElementBounds(x: 100, y: 100, width: 200, height: 50)
let b2 = ElementBounds(x: 100.5, y: 100.4, width: 200.2, height: 50.1)
let b3 = ElementBounds(x: 105, y: 100, width: 200, height: 50)
assert(boundsRoughlyEqual(b1, b2, tolerance: 1.0))
assert(!boundsRoughlyEqual(b1, b3, tolerance: 1.0))

let mSearch1 = OCRMatch(text: "Search", confidence: 0.95, bounds: b1, desktopX: 150, desktopY: 125)
let mSearch2 = OCRMatch(text: "Search More", confidence: 0.90, bounds: b1, desktopX: 180, desktopY: 125)
let mSubmit1 = OCRMatch(text: "Submit", confidence: 0.99, bounds: b1, desktopX: 200, desktopY: 125)
let mSubmit2 = OCRMatch(text: "Submit", confidence: 0.98, bounds: b1, desktopX: 300, desktopY: 125)

// Substring match ambiguity
let filteredSearch = filterOCRMatches([mSearch1, mSearch2], query: "Search", exact: false)
assert(filteredSearch.count == 2)
do {
    _ = try resolveOCRTargetFromMatches(filteredSearch, query: "Search")
    assert(false, "Should have thrown ambiguous")
} catch OCRError.ambiguous(_, let count, _) {
    assert(count == 2)
} catch {
    assert(false, "Unexpected error: \(error)")
}

// Exact match with duplicate text still ambiguous
let filteredSubmit = filterOCRMatches([mSubmit1, mSubmit2], query: "Submit", exact: true)
assert(filteredSubmit.count == 2)
do {
    _ = try resolveOCRTargetFromMatches(filteredSubmit, query: "Submit")
    assert(false, "Exact duplicates should have thrown ambiguous")
} catch OCRError.ambiguous(_, let count, _) {
    assert(count == 2)
} catch {
    assert(false, "Unexpected error: \(error)")
}

// Disambiguation with occurrence
let resolvedOcc1 = try! resolveOCRTargetFromMatches(filteredSubmit, query: "Submit", occurrence: 1)
assert(resolvedOcc1.desktopX == 200)
let resolvedOcc2 = try! resolveOCRTargetFromMatches(filteredSubmit, query: "Submit", occurrence: 2)
assert(resolvedOcc2.desktopX == 300)

// Out of bounds occurrence
do {
    _ = try resolveOCRTargetFromMatches(filteredSubmit, query: "Submit", occurrence: 3)
    assert(false, "Occurrence 3 should have thrown outOfBounds")
} catch OCRError.outOfBounds(let occ, let count) {
    assert(occ == 3 && count == 2)
} catch {
    assert(false, "Unexpected error: \(error)")
}

print("POLICY_CHECKS_PASSED")

