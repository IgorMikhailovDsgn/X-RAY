import XCTest
@testable import BrainScan

final class TokenStoreTests: XCTestCase {
    private var store: TokenStore!
    private var keychain: Keychain!

    override func setUp() {
        super.setUp()
        keychain = Keychain(service: "com.brainscan.client.tests.\(UUID().uuidString)")
        store = TokenStore(keychain: keychain)
    }

    func test_load_returns_nil_when_empty() throws {
        XCTAssertNil(try store.load())
    }

    func test_save_then_load_roundtrip() throws {
        let original = TokenPair(
            accessToken: "access-jwt",
            refreshToken: "refresh-jwt",
            expiresIn: 900,
            issuedAt: Date(timeIntervalSince1970: 1_700_000_000)
        )
        try store.save(original)
        let loaded = try XCTUnwrap(try store.load())
        XCTAssertEqual(loaded.accessToken, "access-jwt")
        XCTAssertEqual(loaded.refreshToken, "refresh-jwt")
        XCTAssertEqual(loaded.expiresIn, 900)
        XCTAssertEqual(loaded.issuedAt.timeIntervalSince1970, 1_700_000_000, accuracy: 0.001)
    }

    func test_clear_removes_pair() throws {
        try store.save(.fixture)
        try store.clear()
        XCTAssertNil(try store.load())
    }

    func test_isAccessExpired_returns_false_when_fresh() {
        let pair = TokenPair(
            accessToken: "a", refreshToken: "r",
            expiresIn: 900,
            issuedAt: Date(timeIntervalSince1970: 1_700_000_000)
        )
        // запас 30s; токен живёт 900s; «сейчас» = +60s от issuedAt
        let now = Date(timeIntervalSince1970: 1_700_000_060)
        XCTAssertFalse(pair.isAccessExpired(now: now))
    }

    func test_isAccessExpired_returns_true_inside_buffer() {
        // Запас 30s: токен формально живёт ещё 20s — считаем истёкшим.
        let pair = TokenPair(
            accessToken: "a", refreshToken: "r",
            expiresIn: 900,
            issuedAt: Date(timeIntervalSince1970: 1_700_000_000)
        )
        let now = Date(timeIntervalSince1970: 1_700_000_880)  // exp = +900
        XCTAssertTrue(pair.isAccessExpired(now: now))
    }
}

private extension TokenPair {
    static let fixture = TokenPair(
        accessToken: "fixture-access",
        refreshToken: "fixture-refresh",
        expiresIn: 900
    )
}
