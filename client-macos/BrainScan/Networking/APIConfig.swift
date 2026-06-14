import Foundation

/// Базовый URL API подтягивается из `Info.plist` (ключ `BrainScanAPIBaseURL`),
/// который заполняется build-настройкой `BRAINSCAN_API_BASE_URL` per-config.
/// Конфигурации описаны в [client-macos/project.yml](../../project.yml).
enum APIConfig {
    static let baseURL: URL = {
        guard
            let raw = Bundle.main.object(forInfoDictionaryKey: "BrainScanAPIBaseURL") as? String,
            !raw.isEmpty,
            let url = URL(string: raw)
        else {
            fatalError(
                "BrainScanAPIBaseURL missing or invalid in Info.plist; "
                + "check BRAINSCAN_API_BASE_URL build setting."
            )
        }
        return url
    }()
}
