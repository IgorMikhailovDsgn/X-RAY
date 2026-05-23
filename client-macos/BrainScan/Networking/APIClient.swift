import Foundation

/// Ошибки сетевого слоя — пользовательско-понятные сообщения через `LocalizedError`,
/// чтобы UI просто показывал `error.errorDescription`.
enum APIError: Error, LocalizedError {
    case network(Error)
    case http(status: Int, message: String?)
    case decoding(Error)
    case invalidResponse
    case unauthorized
    case encoding(Error)

    var errorDescription: String? {
        switch self {
        case .network: return "Network error. Check your connection."
        case let .http(status, message):
            if status == 401 { return "Session expired. Please sign in again." }
            if status == 422 { return message ?? "Please check the data and try again." }
            return message ?? "Server error (\(status))."
        case .decoding: return "Unexpected response from server."
        case .invalidResponse: return "Invalid response from server."
        case .unauthorized: return "Session expired. Please sign in again."
        case .encoding: return "Could not encode request."
        }
    }
}

/// HTTP-клиент к BrainScan API. Bearer-токен подтягивается из `TokenStore` для
/// защищённых эндпоинтов. Refresh-on-401 пока не реализован (отдельный слайс).
final class APIClient {
    static let shared = APIClient()

    private let baseURL: URL
    private let session: URLSession
    private let tokenStore: TokenStore
    private let encoder: JSONEncoder
    private let decoder: JSONDecoder

    init(baseURL: URL = APIConfig.baseURL,
         session: URLSession = .shared,
         tokenStore: TokenStore = TokenStore()) {
        self.baseURL = baseURL
        self.session = session
        self.tokenStore = tokenStore
        encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        encoder.dateEncodingStrategy = .iso8601
        decoder = JSONDecoder()
        // Не используем convertFromSnakeCase: у `TokenPair` есть собственные
        // CodingKeys со snake_case-ключами, и стратегия их ломает (трансформирует
        // ключ до сверки). Остальные response-DTO имеют только `id`.
        decoder.dateDecodingStrategy = .iso8601
    }

    // MARK: - Auth

    struct LoginRequest: Encodable { let email: String; let password: String }

    func login(email: String, password: String) async throws -> TokenPair {
        try await sendJSON(method: "POST", path: "auth/login",
                           body: LoginRequest(email: email, password: password),
                           authorized: false)
    }

    // MARK: - Health / Models

    struct HealthResponse: Decodable { let status: String }

    func health() async throws -> HealthResponse {
        try await sendGET(path: "health", authorized: false)
    }

    struct ModelsResponse: Decodable { let models: [DeployedModel] }
    struct DeployedModel: Decodable {
        let modelType: String
        let version: String
        enum CodingKeys: String, CodingKey {
            case modelType = "model_type"
            case version
        }
    }

    func modelsDeployed() async throws -> ModelsResponse {
        try await sendGET(path: "models/deployed", authorized: true)
    }

    // MARK: - Screenshots / Annotations (Annotate cold start)

    struct ScreenshotsResponse: Decodable { let id: UUID }

    /// Загрузка скриншотов всех мониторов одной сессии (multipart). Возвращает screen_id.
    func uploadScreenshots(images: [Int: Data]) async throws -> ScreenshotsResponse {
        var body = MultipartBody()
        let meta = "{\"device_id\":\"\(DeviceID.value)\",\"monitor_count\":\(images.count)}"
        body.appendField(name: "meta", value: meta)
        for (index, png) in images.sorted(by: { $0.key < $1.key }) {
            body.appendFile(name: "screen_\(index)", filename: "screen_\(index).png",
                            contentType: "image/png", data: png)
        }
        body.finalize()
        return try await sendMultipart(path: "screenshots", body: body)
    }

    struct LocalizeAnnotationCreate: Encodable {
        let screenId: UUID
        let detectionId: UUID?
        let monitorIndex: Int
        let bbox: BboxDTO?
        let action: String
    }
    struct LocalizeAnnotationResponse: Decodable { let id: UUID }

    func createLocalizeAnnotation(_ req: LocalizeAnnotationCreate)
        async throws -> LocalizeAnnotationResponse {
        try await sendJSON(method: "POST", path: "localize-annotations", body: req, authorized: true)
    }

    struct LocalizeImageResponse: Decodable { let id: UUID }

    func uploadLocalizeImage(
        screenId: UUID, monitorIndex: Int, bbox: BboxDTO,
        detectionId: UUID? = nil, annotationId: UUID? = nil, crop: Data
    ) async throws -> LocalizeImageResponse {
        var meta: [String: Any] = [
            "screen_id": screenId.uuidString,
            "monitor_index": monitorIndex,
            "bbox": ["x": bbox.x, "y": bbox.y, "w": bbox.w, "h": bbox.h],
        ]
        if let detectionId { meta["detection_id"] = detectionId.uuidString }
        if let annotationId { meta["annotation_id"] = annotationId.uuidString }
        let metaJSON = try JSONSerialization.data(withJSONObject: meta)
        var body = MultipartBody()
        body.appendField(name: "meta", value: String(data: metaJSON, encoding: .utf8) ?? "{}")
        body.appendFile(name: "crop", filename: "crop.png", contentType: "image/png", data: crop)
        body.finalize()
        return try await sendMultipart(path: "localize-images", body: body)
    }

    struct TumorAnnotationCreate: Encodable {
        let localizeImageId: UUID
        let detectionId: UUID?
        let bbox: BboxDTO?
        let action: String
    }
    struct TumorAnnotationResponse: Decodable { let id: UUID }

    func createTumorAnnotation(_ req: TumorAnnotationCreate) async throws -> TumorAnnotationResponse {
        try await sendJSON(method: "POST", path: "tumor-annotations", body: req, authorized: true)
    }

    // MARK: - Helpers

    private func sendJSON<Req: Encodable, Resp: Decodable>(
        method: String, path: String, body: Req?, authorized: Bool
    ) async throws -> Resp {
        var request = URLRequest(url: baseURL.appendingPathComponent(path))
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if authorized { try injectBearer(&request) }
        if let body {
            do { request.httpBody = try encoder.encode(body) }
            catch { throw APIError.encoding(error) }
        }
        return try await perform(request)
    }

    private func sendGET<Resp: Decodable>(path: String, authorized: Bool) async throws -> Resp {
        var request = URLRequest(url: baseURL.appendingPathComponent(path))
        request.httpMethod = "GET"
        if authorized { try injectBearer(&request) }
        return try await perform(request)
    }

    private func sendMultipart<Resp: Decodable>(
        path: String, body: MultipartBody
    ) async throws -> Resp {
        var request = URLRequest(url: baseURL.appendingPathComponent(path))
        request.httpMethod = "POST"
        request.setValue(body.contentType, forHTTPHeaderField: "Content-Type")
        try injectBearer(&request)
        request.httpBody = body.data
        return try await perform(request)
    }

    private func injectBearer(_ request: inout URLRequest) throws {
        guard let pair = try tokenStore.load() else { throw APIError.unauthorized }
        request.setValue("Bearer \(pair.accessToken)", forHTTPHeaderField: "Authorization")
    }

    private func perform<Resp: Decodable>(_ request: URLRequest) async throws -> Resp {
        let data: Data
        let response: URLResponse
        do { (data, response) = try await session.data(for: request) }
        catch { throw APIError.network(error) }
        guard let http = response as? HTTPURLResponse else { throw APIError.invalidResponse }
        guard 200..<300 ~= http.statusCode else {
            throw APIError.http(status: http.statusCode, message: parseErrorMessage(data))
        }
        do { return try decoder.decode(Resp.self, from: data) }
        catch { throw APIError.decoding(error) }
    }

    private func parseErrorMessage(_ data: Data) -> String? {
        struct ErrorBody: Decodable { let detail: String? }
        return (try? JSONDecoder().decode(ErrorBody.self, from: data))?.detail
    }
}

/// Bbox в API — целочисленные пиксели `{x, y, w, h}` (`shared/openapi.yaml`).
struct BboxDTO: Codable {
    let x: Int
    let y: Int
    let w: Int
    let h: Int

    init(physical rect: CGRect) {
        x = max(0, Int(rect.origin.x.rounded()))
        y = max(0, Int(rect.origin.y.rounded()))
        w = max(1, Int(rect.width.rounded()))
        h = max(1, Int(rect.height.rounded()))
    }
}
