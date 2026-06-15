import Foundation

/// Скользящий таймер бездействия. Жизненный цикл — пока юзер залогинен.
/// Триггерится из AppDelegate (юзерские action handlers зовут `markActive()`),
/// проверяется периодическим Timer'ом — при `isExpired(threshold:)` AppDelegate
/// дергает `signOut()` и виджет переходит в Sign In.
///
/// Background-pollers (StatusPoller, sync drain) НЕ помечают активность —
/// иначе пользователь будет вечно «активным» и таймер не сработает.
final class SessionActivity {
    static let shared = SessionActivity()

    private let queue = DispatchQueue(label: "BrainScan.SessionActivity")
    private var _lastActiveAt: Date = .init()

    var lastActiveAt: Date {
        queue.sync { _lastActiveAt }
    }

    func markActive(now: Date = .init()) {
        queue.sync { _lastActiveAt = now }
    }

    /// Сброс таймера в «сейчас» — вызывается при свежем sign-in,
    /// чтобы только что вошедший пользователь не оказался сразу «idle».
    func reset(now: Date = .init()) {
        markActive(now: now)
    }

    /// 15-min default = бизнес-требование «протухает после 15 минут бездействия».
    /// Меньше TTL access-токена (30 мин) — пользователь успеет переавторизоваться
    /// до того, как сервер сам ответит 401.
    func isExpired(threshold: TimeInterval = 15 * 60, now: Date = .init()) -> Bool {
        now.timeIntervalSince(lastActiveAt) >= threshold
    }
}

extension Notification.Name {
    /// Постит APIClient при 401 (либо AppDelegate сам при срабатывании
    /// inactivity timer). Подписчик — AppDelegate, дергает signOut().
    static let userSessionExpired = Notification.Name("BrainScan.userSessionExpired")
}
