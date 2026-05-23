import AppKit
import Carbon.HIToolbox

/// Системные хоткеи через Carbon `RegisterEventHotKey` — срабатывают вне фокуса
/// приложения (LSUIElement не делает app активным без явных команд). Без сторонних
/// зависимостей и без необходимости в Accessibility-доступе.
///
/// `setEnabled(false)` снимает все регистрации (тогл «Keyboard shortcuts» в Settings),
/// `true` — регистрирует заново.
final class GlobalHotkeyManager {
    struct Spec {
        let id: UInt32
        let keyCode: UInt32
        let modifiers: UInt32
        let handler: () -> Void
    }

    private var specs: [Spec] = []
    private var refs: [UInt32: EventHotKeyRef] = [:]
    private var handlers: [UInt32: () -> Void] = [:]
    private var eventHandler: EventHandlerRef?
    private var enabled = true

    func install(_ specs: [Spec]) {
        unregisterAll()
        self.specs = specs
        self.handlers = Dictionary(uniqueKeysWithValues: specs.map { ($0.id, $0.handler) })
        installEventHandlerIfNeeded()
        if enabled { registerAll() }
    }

    func setEnabled(_ on: Bool) {
        guard enabled != on else { return }
        enabled = on
        if on { registerAll() } else { unregisterAll() }
    }

    deinit {
        unregisterAll()
        if let h = eventHandler { RemoveEventHandler(h) }
    }

    // MARK: - Carbon

    private func installEventHandlerIfNeeded() {
        guard eventHandler == nil else { return }
        var spec = EventTypeSpec(eventClass: OSType(kEventClassKeyboard),
                                 eventKind: UInt32(kEventHotKeyPressed))
        let ptr = Unmanaged.passUnretained(self).toOpaque()
        InstallEventHandler(GetApplicationEventTarget(), { _, event, userData in
            guard let event, let userData else { return noErr }
            let me = Unmanaged<GlobalHotkeyManager>.fromOpaque(userData).takeUnretainedValue()
            var hkID = EventHotKeyID()
            let size = MemoryLayout<EventHotKeyID>.size
            GetEventParameter(event, EventParamName(kEventParamDirectObject),
                              EventParamType(typeEventHotKeyID), nil, size, nil, &hkID)
            let handler = me.handlers[hkID.id]
            DispatchQueue.main.async { handler?() }
            return noErr
        }, 1, &spec, ptr, &eventHandler)
    }

    private func registerAll() {
        for spec in specs {
            var ref: EventHotKeyRef?
            let hkID = EventHotKeyID(signature: OSType(0x42525354), id: spec.id)   // 'BRST'
            let status = RegisterEventHotKey(spec.keyCode, spec.modifiers, hkID,
                                             GetApplicationEventTarget(), 0, &ref)
            if status == noErr, let ref { refs[spec.id] = ref }
        }
    }

    private func unregisterAll() {
        for ref in refs.values { UnregisterEventHotKey(ref) }
        refs.removeAll()
    }
}
