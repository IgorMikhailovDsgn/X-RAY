import Foundation

/// DTO от `/api/v1/auth/login|register|refresh`.
/// `accessToken` короткоживущий (по умолчанию 15 минут), `refreshToken` — 30 дней.
struct TokenPair: Codable, Equatable {
    let accessToken: String
    let refreshToken: String
    let tokenType: String
    let expiresIn: Int       // TTL access токена в секундах (приходит с сервера)
    let issuedAt: Date       // момент сохранения у клиента — для расчёта exp локально

    enum CodingKeys: String, CodingKey {
        case accessToken = "access_token"
        case refreshToken = "refresh_token"
        case tokenType = "token_type"
        case expiresIn = "expires_in"
        case issuedAt
    }

    init(
        accessToken: String,
        refreshToken: String,
        tokenType: String = "bearer",
        expiresIn: Int,
        issuedAt: Date = .init()
    ) {
        self.accessToken = accessToken
        self.refreshToken = refreshToken
        self.tokenType = tokenType
        self.expiresIn = expiresIn
        self.issuedAt = issuedAt
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        accessToken = try c.decode(String.self, forKey: .accessToken)
        refreshToken = try c.decode(String.self, forKey: .refreshToken)
        tokenType = try c.decodeIfPresent(String.self, forKey: .tokenType) ?? "bearer"
        expiresIn = try c.decode(Int.self, forKey: .expiresIn)
        // issuedAt сервером не передаётся: при дешифровке свежего ответа берём «сейчас»,
        // при load() из Keychain — поле уже сохранено.
        issuedAt = try c.decodeIfPresent(Date.self, forKey: .issuedAt) ?? .init()
    }

    var accessExpiresAt: Date {
        issuedAt.addingTimeInterval(TimeInterval(expiresIn))
    }

    /// Запас в 30 секунд предохраняет от ситуации «токен валиден, пока летит запрос —
    /// истёк, пока сервер его читает».
    func isAccessExpired(buffer: TimeInterval = 30, now: Date = .init()) -> Bool {
        now.addingTimeInterval(buffer) >= accessExpiresAt
    }
}
