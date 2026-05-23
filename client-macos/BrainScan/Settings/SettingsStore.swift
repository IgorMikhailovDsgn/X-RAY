import Combine
import Foundation

/// Персистентные настройки приложения (UserDefaults), observable для SwiftUI и
/// для подписки в AppDelegate. Пока тут единственный реально работающий тогл —
/// «Keyboard shortcuts». Остальные тоглы из `SettingsView` подключим позже.
final class SettingsStore: ObservableObject {
    static let shared = SettingsStore()

    private let defaults = UserDefaults.standard
    private enum Keys {
        static let keyboardShortcuts = "brainscan.keyboardShortcuts"
    }

    @Published var keyboardShortcutsEnabled: Bool {
        didSet { defaults.set(keyboardShortcutsEnabled, forKey: Keys.keyboardShortcuts) }
    }

    private init() {
        keyboardShortcutsEnabled =
            (defaults.object(forKey: Keys.keyboardShortcuts) as? Bool) ?? true
    }
}
