import AppKit

/// Управляет detect-оверлеем на всех мониторах: скрим + HUD + предсказания.
/// Не мутирует модель — это визуальный слой Detect-режима.
final class DetectOverlayController {
    private var windows: [Int: DetectOverlayWindow] = [:]
    private var views: [Int: DetectOverlayView] = [:]
    private var mainIndex = 0

    var isPresented: Bool { !windows.isEmpty }
    var mainMonitorIndex: Int { mainIndex }
    var mainMonitorSize: CGSize { NSScreen.main?.frame.size ?? .init(width: 1440, height: 900) }

    func present() {
        guard windows.isEmpty else { return }
        for (index, screen) in NSScreen.screens.enumerated() {
            let isMain = screen == NSScreen.main
            if isMain { mainIndex = index }
            let window = DetectOverlayWindow(frame: screen.frame, isMain: isMain)
            windows[index] = window
            views[index] = window.overlayView
            window.orderFrontRegardless()
        }
    }

    func dismiss() {
        for window in windows.values { window.orderOut(nil) }
        windows.removeAll()
        views.removeAll()
    }

    // MARK: - Фазы

    func showDetecting() {
        setScrim(0.40)
        clearPredictions()
        mainView?.showDetecting(title: "Detecting…")
    }

    func showLongerMessage() {
        mainView?.setDetectingTitle("It takes longer than usual…")
    }

    func showResult(_ result: DetectResult) {
        setScrim(0.70)   // как и при regions not found
        mainView?.clearHUD()
        for prediction in result.predictions {
            views[prediction.monitorIndex]?.setPredictions(
                region: prediction.regions,
                tumor: prediction.tumors
            )
        }
    }

    func showRegionsNotFound() {
        setScrim(0.70)
        clearPredictions()
        mainView?.showNotFound(title: "Regions not found")
    }

    // MARK: - Внутреннее

    private var mainView: DetectOverlayView? { views[mainIndex] }

    private func setScrim(_ alpha: CGFloat) {
        views.values.forEach { $0.setScrim(alpha) }
    }

    private func clearPredictions() {
        views.values.forEach { $0.setPredictions(region: [], tumor: []) }
    }
}
