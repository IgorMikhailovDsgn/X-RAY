import Foundation

/// Хранит JWT-пару в Keychain. Source-of-truth для авторизованного состояния.
/// API-клиент (Phase C step 3) будет читать access-токен отсюда перед каждым запросом
/// и вызывать refresh при `isAccessExpired`.
final class TokenStore {
    private let keychain: Keychain
    private let account = "auth.tokens.v1"
    private let encoder: JSONEncoder
    private let decoder: JSONDecoder

    init(keychain: Keychain = Keychain()) {
        self.keychain = keychain
        self.encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        self.decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
    }

    func save(_ pair: TokenPair) throws {
        let data = try encoder.encode(pair)
        guard let json = String(data: data, encoding: .utf8) else {
            throw KeychainError.decodingFailed
        }
        try keychain.set(json, for: account)
    }

    func load() throws -> TokenPair? {
        guard
            let json = try keychain.get(account),
            let data = json.data(using: .utf8)
        else {
            return nil
        }
        return try decoder.decode(TokenPair.self, from: data)
    }

    func clear() throws {
        try keychain.delete(account)
    }
}
