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
assert(computeDiff(oldLines: ["A"], newLines: ["A"]) == "(no visible UI changes)")
print("POLICY_CHECKS_PASSED")
