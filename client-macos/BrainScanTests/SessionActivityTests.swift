import XCTest
@testable import BrainScan

final class SessionActivityTests: XCTestCase {
    private var sut: SessionActivity!

    override func setUp() {
        super.setUp()
        sut = SessionActivity.shared
        sut.reset(now: .init())
    }

    func test_fresh_session_is_not_expired() {
        XCTAssertFalse(sut.isExpired(threshold: 60, now: .init()))
    }

    func test_after_threshold_isExpired_true() {
        let t0 = Date(timeIntervalSince1970: 1_000_000)
        sut.markActive(now: t0)
        XCTAssertTrue(sut.isExpired(threshold: 60, now: t0.addingTimeInterval(61)))
    }

    func test_just_before_threshold_isExpired_false() {
        let t0 = Date(timeIntervalSince1970: 1_000_000)
        sut.markActive(now: t0)
        XCTAssertFalse(sut.isExpired(threshold: 60, now: t0.addingTimeInterval(59)))
    }

    func test_markActive_resets_clock() {
        let t0 = Date(timeIntervalSince1970: 1_000_000)
        sut.markActive(now: t0)
        // Прошло почти всё окно — но markActive сдвигает «сейчас» в новый момент.
        let t1 = t0.addingTimeInterval(59)
        sut.markActive(now: t1)
        // Теперь относительно t1+59 — снова в пределах окна.
        XCTAssertFalse(sut.isExpired(threshold: 60, now: t1.addingTimeInterval(59)))
        XCTAssertTrue(sut.isExpired(threshold: 60, now: t1.addingTimeInterval(61)))
    }

    func test_reset_sets_lastActive_to_passed_date() {
        let target = Date(timeIntervalSince1970: 2_000_000)
        sut.reset(now: target)
        XCTAssertEqual(sut.lastActiveAt, target)
    }
}
