import AppKit
import CoreImage
import CoreMedia
import ScreenCaptureKit

/// Геометрия + (опционально) пиксели одного дисплея. При показе оверлея
/// заполняется только геометрия (`image == nil`) — захват экрана делается
/// отдельно в момент Send, без замороженного фона.
struct DisplaySnapshot {
    let displayID: CGDirectDisplayID
    let monitorIndex: Int
    /// Пиксели дисплея. nil, пока не сделан реальный захват (на Send).
    let image: CGImage?
    /// Глобальный frame дисплея в logical-точках (как у NSScreen.frame).
    let frame: CGRect
    /// dpi_scale_factor монитора (2.0 для Retina) — для конвертации в physical.
    let scaleFactor: CGFloat
}

enum ScreenCaptureError: Error {
    case permissionDenied
    case noDisplays
    case captureFailed
}

/// Захват всех мониторов через ScreenCaptureKit. Снимок делается один раз при
/// открытии оверлея и далее показывается как замороженный фон. Окна нашего
/// приложения (виджет/тулбар) исключаются из кадра.
enum ScreenCapturer {
    /// Есть ли уже разрешение Screen Recording.
    static func hasPermission() -> Bool {
        CGPreflightScreenCaptureAccess()
    }

    /// Запросить разрешение (системный промпт при первом вызове).
    @discardableResult
    static func requestPermission() -> Bool {
        CGRequestScreenCaptureAccess()
    }

    static func captureAll() async throws -> [DisplaySnapshot] {
        // Не полагаемся на CGPreflight (бывает несинхронным). Источник правды —
        // сама попытка через ScreenCaptureKit: при «not determined» она показывает
        // системный промпт, при отказе бросает ошибку → трактуем как permissionDenied.
        let content: SCShareableContent
        do {
            content = try await shareableContent()
        } catch {
            throw ScreenCaptureError.permissionDenied
        }
        guard !content.displays.isEmpty else { throw ScreenCaptureError.permissionDenied }

        let ownBundleID = Bundle.main.bundleIdentifier
        let ownWindows = content.windows.filter {
            $0.owningApplication?.bundleIdentifier == ownBundleID
        }

        var snapshots: [DisplaySnapshot] = []
        for (index, display) in content.displays.enumerated() {
            let filter = SCContentFilter(display: display, excludingWindows: ownWindows)
            let image = try await captureImage(filter: filter, display: display)
            let screen = nsScreen(for: display.displayID)
            snapshots.append(
                DisplaySnapshot(
                    displayID: display.displayID,
                    monitorIndex: index,
                    image: image,
                    frame: screen?.frame ?? CGRect(x: 0, y: 0,
                                                   width: display.width, height: display.height),
                    scaleFactor: screen?.backingScaleFactor ?? 1.0
                )
            )
        }
        return snapshots
    }

    // MARK: - ScreenCaptureKit version split

    private static func captureImage(filter: SCContentFilter,
                                     display: SCDisplay) async throws -> CGImage {
        let config = SCStreamConfiguration()
        config.width = display.width * 2     // запас под Retina; ширина в physical px
        config.height = display.height * 2
        config.showsCursor = false

        if #available(macOS 14.0, *) {
            return try await SCScreenshotManager.captureImage(
                contentFilter: filter, configuration: config
            )
        } else {
            return try await OneShotStreamCapturer.capture(filter: filter, configuration: config)
        }
    }

    private static func shareableContent() async throws -> SCShareableContent {
        try await withCheckedThrowingContinuation { cont in
            SCShareableContent.getExcludingDesktopWindows(
                false, onScreenWindowsOnly: true
            ) { content, error in
                if let content {
                    cont.resume(returning: content)
                } else {
                    cont.resume(throwing: error ?? ScreenCaptureError.captureFailed)
                }
            }
        }
    }

    private static func nsScreen(for displayID: CGDirectDisplayID) -> NSScreen? {
        NSScreen.screens.first {
            let key = NSDeviceDescriptionKey("NSScreenNumber")
            return ($0.deviceDescription[key] as? CGDirectDisplayID) == displayID
        }
    }
}

/// Фолбэк для macOS 12.3–13, где нет `SCScreenshotManager`: запускаем `SCStream`,
/// берём первый кадр и сразу останавливаем поток.
@available(macOS 12.3, *)
private final class OneShotStreamCapturer: NSObject, SCStreamOutput {
    private var continuation: CheckedContinuation<CGImage, Error>?
    private var stream: SCStream?
    private let queue = DispatchQueue(label: "com.brainscan.oneshot-capture")
    private var finished = false

    static func capture(filter: SCContentFilter,
                        configuration: SCStreamConfiguration) async throws -> CGImage {
        let capturer = OneShotStreamCapturer()
        return try await capturer.run(filter: filter, configuration: configuration)
    }

    private func run(filter: SCContentFilter,
                     configuration: SCStreamConfiguration) async throws -> CGImage {
        try await withCheckedThrowingContinuation { cont in
            self.continuation = cont
            do {
                let stream = SCStream(filter: filter, configuration: configuration, delegate: nil)
                try stream.addStreamOutput(self, type: .screen, sampleHandlerQueue: queue)
                self.stream = stream
                stream.startCapture { error in
                    if let error { self.finish(.failure(error)) }
                }
            } catch {
                cont.resume(throwing: error)
                self.continuation = nil
            }
        }
    }

    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer,
                of type: SCStreamOutputType) {
        guard type == .screen,
              let pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        let ciImage = CIImage(cvPixelBuffer: pixelBuffer)
        let context = CIContext()
        guard let cgImage = context.createCGImage(ciImage, from: ciImage.extent) else { return }
        finish(.success(cgImage))
    }

    private func finish(_ result: Result<CGImage, Error>) {
        queue.async {
            guard !self.finished else { return }
            self.finished = true
            self.stream?.stopCapture { _ in }
            self.stream = nil
            switch result {
            case let .success(image): self.continuation?.resume(returning: image)
            case let .failure(error): self.continuation?.resume(throwing: error)
            }
            self.continuation = nil
        }
    }
}
