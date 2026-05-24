import AppKit
import Carbon.HIToolbox
import Combine

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    private var menubar: MenubarController?
    private var widget: DefaultWidgetController?
    private let settings = SettingsWindowController()
    private let signIn = SignInWindowController()
    private let annotate = AnnotateController()
    private let detect = DetectController()
    private let hotkeys = GlobalHotkeyManager()
    private let tokenStore = TokenStore()
    private let poller = StatusPoller()
    private var cancellables = Set<AnyCancellable>()
    private var isSignedIn = false

    func applicationDidFinishLaunching(_: Notification) {
        // Стартуем с пессимистичного `.noServer` — первый успешный poll заменит.
        let widget = DefaultWidgetController(
            initialStatus: .noServer(localAnnotations: 0)
        )
        widget.onAnnotateClicked = { [weak self] in self?.handleAnnotate() }
        widget.onDetectClicked = { [weak self] in self?.handleDetect() }
        widget.onSettingsClicked = { [weak self] in self?.handleSettings() }
        self.widget = widget

        let menubar = MenubarController()
        menubar.onToggleWidget = { [weak self] in self?.toggleWidget() }
        menubar.onAnnotate = { [weak self] in self?.handleAnnotate() }
        menubar.onDetect = { [weak self] in self?.handleDetect() }
        menubar.onSettings = { [weak self] in self?.handleSettings() }
        self.menubar = menubar

        annotate.onFinished = { [weak self] _ in
            // Правило проекта: виджет всегда возвращается на ту позицию, куда его
            // поставил пользователь (никаких сдвигов из аннотации/детекции).
            self?.widget?.show()
        }
        annotate.onSent = { [weak self] outcome in
            guard let widget = self?.widget else { return }
            let (text, tint): (String, NSColor) = switch outcome {
            case .uploaded: ("Annotations sent", .systemGreen)
            case .queued:   ("Saved offline · will sync", .systemYellow)
            }
            ToastController.shared.show(
                text: text,
                icon: Icon24.check.makeImage(pointSize: 16),
                iconTint: tint,
                near: widget.bodyCenterOnScreen
            )
        }
        detect.onFinished = { [weak self] in self?.widget?.show() }
        detect.onEdit = { [weak self] prefill in
            guard let self, let widget = self.widget else { return }
            self.annotate.start(bodyCenter: widget.bodyCenterOnScreen, prefill: prefill)
        }
        signIn.onSignedIn = { [weak self] in self?.didSignIn() }
        settings.onSignOut = { [weak self] in self?.signOut() }

        installGlobalHotkeys()
        bindWidgetStatus()

        // Гейтинг старта: считаем сессию валидной только если access-токен не истёк.
        // Refresh-on-401 ещё не реализован → даже свежезащиченный access после рестарта
        // часто будет требовать перелогина (TTL ~15 мин). Виджет показываем только
        // после `didSignIn()`, до этого видно только окно входа.
        if let pair = (try? tokenStore.load()) ?? nil, !pair.isAccessExpired() {
            didSignIn()
        } else {
            showSignIn()
        }
    }

    /// Виджет = комбинация серверного статуса и состояния очереди:
    /// дренаж очереди показывает `.syncing(uploaded, total)`, иначе — серверный
    /// статус. `localAnnotations` отражает остаток очереди для .noServer/.noModels.
    /// Дополнительно: переход poller'а в online-состояние триггерит дренаж очереди
    /// (NWPathMonitor видит интерфейс, но не падение сервера, поэтому полагаемся
    /// на /health-ответ как сигнал «сервер вернулся»).
    private func bindWidgetStatus() {
        Publishers.CombineLatest(poller.$serverStatus, SyncManager.shared.$state)
            .receive(on: DispatchQueue.main)
            .sink { [weak self] server, sync in self?.applyWidgetStatus(server: server, sync: sync) }
            .store(in: &cancellables)

        poller.$serverStatus
            .map { status -> Bool in
                if case .connected = status { return true }
                if case .noModels = status { return true }
                return false
            }
            .removeDuplicates()
            .filter { $0 }
            .receive(on: DispatchQueue.main)
            .sink { _ in Task { await SyncManager.shared.attemptDrain() } }
            .store(in: &cancellables)
    }

    private func applyWidgetStatus(server: StatusPoller.ServerStatus,
                                   sync: SyncManager.State) {
        guard let widget else { return }
        let status: WidgetStatus
        if case let .draining(up, total) = sync {
            status = .syncing(uploaded: up, total: total)
        } else {
            let queued: Int
            if case let .queued(count) = sync { queued = count } else { queued = 0 }
            switch server {
            case let .connected(localizer, tumor):
                status = .connected(localizerVersion: localizer, tumorVersion: tumor)
            case .noModels:
                status = .noModels(localAnnotations: queued)
            case .serviceUnavailable:
                status = .serviceUnavailable
            case .noServer:
                status = .noServer(localAnnotations: queued)
            }
        }
        widget.setStatus(status)
        // Тулбары Annotate/Detect показывают такой же dot.
        annotate.setStatusDotColor(status.dotColor)
        detect.setStatusDotColor(status.dotColor)
    }

    // MARK: - Auth lifecycle

    private func didSignIn() {
        isSignedIn = true
        signIn.hide()
        widget?.show()
        poller.start()   // /models/deployed требует Bearer — стартуем после логина.
    }

    private func showSignIn() {
        isSignedIn = false
        widget?.hide()
        signIn.present()
    }

    private func signOut() {
        poller.stop()
        try? tokenStore.clear()
        showSignIn()
    }

    // MARK: - Actions (guarded by sign-in)

    private func handleAnnotate() {
        guard isSignedIn, let widget else { return }
        let center = widget.bodyCenterOnScreen
        widget.hide()
        annotate.start(bodyCenter: center)
    }

    private func handleDetect() {
        guard isSignedIn, let widget, widget.status.isDetectEnabled else { return }
        let center = widget.bodyCenterOnScreen
        widget.hide()
        detect.start(bodyCenter: center)
    }

    private func handleSettings() {
        settings.present()
    }

    private func toggleWidget() {
        guard isSignedIn else { return }
        widget?.toggle()
    }

    // MARK: - Global hotkeys (Settings → Keyboard Shortcuts)

    private func installGlobalHotkeys() {
        let cmdShift = UInt32(cmdKey | shiftKey)
        let cmd = UInt32(cmdKey)
        hotkeys.install([
            // ⇧⌘⏎ — Show widget
            .init(id: 1, keyCode: UInt32(kVK_Return), modifiers: cmdShift) { [weak self] in
                guard let self, self.isSignedIn else { return }
                self.widget?.show()
            },
            // ⇧⌘X — Hide widget
            .init(id: 2, keyCode: UInt32(kVK_ANSI_X), modifiers: cmdShift) { [weak self] in
                guard let self, self.isSignedIn else { return }
                self.widget?.hide()
            },
            // ⌘S — Settings (доступно всегда)
            .init(id: 3, keyCode: UInt32(kVK_ANSI_S), modifiers: cmd) { [weak self] in
                self?.handleSettings()
            },
            // ⌘D — Detect
            .init(id: 4, keyCode: UInt32(kVK_ANSI_D), modifiers: cmd) { [weak self] in
                self?.handleDetect()
            },
            // ⇧⌘A — Annotate
            .init(id: 5, keyCode: UInt32(kVK_ANSI_A), modifiers: cmdShift) { [weak self] in
                self?.handleAnnotate()
            },
        ])

        SettingsStore.shared.$keyboardShortcutsEnabled
            .sink { [weak self] enabled in self?.hotkeys.setEnabled(enabled) }
            .store(in: &cancellables)
    }
}
