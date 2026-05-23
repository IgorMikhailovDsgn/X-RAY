import Foundation

/// Базовая конфигурация сетевого слоя. На MVP — фиксированный dev-URL; продакшн
/// и переключатель окружений добавим, когда появится остальной сетевой слой.
enum APIConfig {
    static let baseURL = URL(string: "http://localhost:8000/api/v1")!
}
