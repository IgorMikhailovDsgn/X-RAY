import Foundation

/// Сборщик `multipart/form-data` для upload-эндпоинтов (`/screenshots`,
/// `/localize-images`). Просто и без зависимостей — пишет CRLF-разделители
/// и финальный `--boundary--` маркер.
struct MultipartBody {
    let boundary: String = "BrainScanBoundary-\(UUID().uuidString)"
    private(set) var data = Data()

    var contentType: String { "multipart/form-data; boundary=\(boundary)" }

    mutating func appendField(name: String, value: String) {
        appendString("--\(boundary)\r\n")
        appendString("Content-Disposition: form-data; name=\"\(name)\"\r\n\r\n")
        appendString(value)
        appendString("\r\n")
    }

    mutating func appendFile(name: String, filename: String, contentType: String, data fileData: Data) {
        appendString("--\(boundary)\r\n")
        appendString("Content-Disposition: form-data; name=\"\(name)\"; filename=\"\(filename)\"\r\n")
        appendString("Content-Type: \(contentType)\r\n\r\n")
        data.append(fileData)
        appendString("\r\n")
    }

    mutating func finalize() {
        appendString("--\(boundary)--\r\n")
    }

    private mutating func appendString(_ string: String) {
        if let bytes = string.data(using: .utf8) { data.append(bytes) }
    }
}
