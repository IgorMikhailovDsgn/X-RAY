import Foundation

/// Стабильный идентификатор инсталла клиента: один раз сгенерили UUID и хранится
/// в `UserDefaults`. Backend использует его как `device_id` в meta скриншотов.
enum DeviceID {
    private static let key = "brainscan.deviceId"

    static var value: String {
        if let saved = UserDefaults.standard.string(forKey: key) { return saved }
        let new = UUID().uuidString
        UserDefaults.standard.set(new, forKey: key)
        return new
    }
}
