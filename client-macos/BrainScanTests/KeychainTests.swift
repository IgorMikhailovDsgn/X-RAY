import XCTest
@testable import BrainScan

final class KeychainTests: XCTestCase {
    // Изолированный service-namespace на каждый прогон, чтобы тесты не
    // зависели от состояния системного Keychain между запусками.
    private let service = "com.brainscan.client.tests.\(UUID().uuidString)"
    private var keychain: Keychain!
    private let account = "unit-test-account"

    override func setUp() {
        super.setUp()
        keychain = Keychain(service: service)
        try? keychain.delete(account)
    }

    override func tearDown() {
        try? keychain.delete(account)
        super.tearDown()
    }

    func test_get_returns_nil_when_missing() throws {
        XCTAssertNil(try keychain.get(account))
    }

    func test_set_then_get_roundtrip() throws {
        try keychain.set("hello", for: account)
        XCTAssertEqual(try keychain.get(account), "hello")
    }

    func test_set_overwrites_existing_value() throws {
        try keychain.set("first", for: account)
        try keychain.set("second", for: account)
        XCTAssertEqual(try keychain.get(account), "second")
    }

    func test_delete_removes_value() throws {
        try keychain.set("hello", for: account)
        try keychain.delete(account)
        XCTAssertNil(try keychain.get(account))
    }

    func test_delete_on_missing_is_noop() throws {
        XCTAssertNoThrow(try keychain.delete(account))
    }
}
