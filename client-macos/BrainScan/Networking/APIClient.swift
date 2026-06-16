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

    // MARK: - Detect annotations batch (Phase 10)

    /// Один region-item в batch'е. Координаты bbox — screen-space физ. пиксели,
    /// как у `localize_detections.bbox`. action — `confirmed | corrected | created`.
    struct LocalizeBatchItem: Encodable {
        let detectionId: UUID?
        let monitorIndex: Int
        let bbox: BboxDTO?
        let action: String
        enum CodingKeys: String, CodingKey {
            case detectionId = "detection_id"
            case monitorIndex = "monitor_index"
            case bbox, action
        }
    }

    /// Один tumor-item в batch'е. Координаты bbox — crop-space (привязка к
    /// region'у через индекс в массиве localize[]).
    struct TumorBatchItem: Encodable {
        let regionIndex: Int
        let detectionId: UUID?
        let bbox: BboxDTO?
        let action: String
        enum CodingKeys: String, CodingKey {
            case regionIndex = "region_index"
            case detectionId = "detection_id"
            case bbox, action
        }
    }

    struct BatchAnnotationsRequest: Encodable {
        let screenId: UUID
        let localize: [LocalizeBatchItem]
        let tumors: [TumorBatchItem]
        enum CodingKeys: String, CodingKey {
            case screenId = "screen_id"
            case localize, tumors
        }
    }

    struct BatchAnnotationsResponse: Decodable {
        let localize: [BatchLocalizeAnnotation]
        let tumors: [BatchTumorAnnotation]
    }

    struct BatchLocalizeAnnotation: Decodable {
        let id: UUID
        let action: String
        let correctionType: String?
        let trainingWeight: Double
        enum CodingKeys: String, CodingKey {
            case id, action
            case correctionType = "correction_type"
            case trainingWeight = "training_weight"
        }
    }

    struct BatchTumorAnnotation: Decodable {
        let id: UUID
        let action: String
        let correctionType: String?
        let trainingWeight: Double
        enum CodingKeys: String, CodingKey {
            case id, action
            case correctionType = "correction_type"
            case trainingWeight = "training_weight"
        }
    }

    func batchAnnotations(_ req: BatchAnnotationsRequest) async throws -> BatchAnnotationsResponse {
        try await sendJSON(
            method: "POST", path: "detect/annotations", body: req, authorized: true
        )
    }

    // MARK: - Detect (Phase 9)

    struct DetectRequest: Encodable {
        let screenshotId: UUID
        let monitorIndex: Int
    }

    /// Один bbox от модели в координатах исходного screenshot'а (физические
    /// пиксели, top-left origin). `detectionId` (Phase 10) ссылается на
    /// строку `*_detections`, созданную `/detect`. Клиент использует её при
    /// последующем Approve/Edit, чтобы сервер мог посчитать correction_type.
    struct BBoxResultDTO: Decodable {
        let x: Int
        let y: Int
        let w: Int
        let h: Int
        let confidence: Double
        let detectionId: UUID?
        enum CodingKeys: String, CodingKey {
            case x, y, w, h, confidence
            case detectionId = "detection_id"
        }
    }

    /// Один найденный регион + опциональная вложенная опухоль. `tumor.x/y`
    /// уже сдвинуты на `region.x/y` сервером (в координатах исходного скрина).
    struct RegionPredictionDTO: Decodable {
        let region: BBoxResultDTO
        let tumor: BBoxResultDTO?
    }

    struct DetectResponse: Decodable {
        let screenshotId: UUID
        let monitorIndex: Int
        let localizeModelVersion: String?
        let tumorModelVersion: String?
        let regions: [RegionPredictionDTO]
        enum CodingKeys: String, CodingKey {
            case screenshotId = "screenshot_id"
            case monitorIndex = "monitor_index"
            case localizeModelVersion = "localize_model_version"
            case tumorModelVersion = "tumor_model_version"
            case regions
        }
    }

    func detect(screenshotId: UUID, monitorIndex: Int) async throws -> DetectResponse {
        try await sendJSON(
            method: "POST", path: "detect",
            body: DetectRequest(screenshotId: screenshotId, monitorIndex: monitorIndex),
            authorized: true
        )
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
            // 401 = сервер отверг токен. Просим AppDelegate сразу перевести
            // виджет в Sign In — иначе пользователь будет тыкать и получать
            // невнятные ошибки. Нотификация идёт даже для запросов от пуллеров.
            if http.statusCode == 401 {
                NotificationCenter.default.post(
                    name: .userSessionExpired, object: nil
                )
            }
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
