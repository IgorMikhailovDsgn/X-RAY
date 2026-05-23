import AppKit
import Foundation

/// Файловая очередь оффлайн-разметок: `Application Support/BrainScan/sync_queue/<id>/`
/// с `manifest.json` и `screen_*.png`. Простая и наглядная: один элемент = одна папка.
final class SyncStore {
    private let root: URL
    private let encoder: JSONEncoder
    private let decoder: JSONDecoder

    init() throws {
        let support = try FileManager.default.url(for: .applicationSupportDirectory,
                                                  in: .userDomainMask, appropriateFor: nil,
                                                  create: true)
        root = support.appendingPathComponent("BrainScan/sync_queue", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
    }

    /// Загружено в очередь: манифест + PNG'ы. Возвращает папку элемента.
    @discardableResult
    func enqueue(manifest: SyncManifest, images: [Int: Data]) throws -> URL {
        let folder = root.appendingPathComponent(manifest.id.uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        try encoder.encode(manifest).write(to: folder.appendingPathComponent("manifest.json"))
        for (index, png) in images {
            try png.write(to: folder.appendingPathComponent("screen_\(index).png"))
        }
        return folder
    }

    /// Все ожидающие элементы, отсортированы по `createdAt`.
    func pending() throws -> [SyncManifest] {
        let folders = (try? FileManager.default.contentsOfDirectory(
            at: root, includingPropertiesForKeys: nil)) ?? []
        var manifests: [SyncManifest] = []
        for folder in folders {
            let url = folder.appendingPathComponent("manifest.json")
            guard let data = try? Data(contentsOf: url) else { continue }
            if let m = try? decoder.decode(SyncManifest.self, from: data) { manifests.append(m) }
        }
        return manifests.sorted { $0.createdAt < $1.createdAt }
    }

    /// Загрузить PNG монитора с диска.
    func loadImage(itemID: UUID, monitorIndex: Int) -> Data? {
        let url = root.appendingPathComponent(
            "\(itemID.uuidString)/screen_\(monitorIndex).png"
        )
        return try? Data(contentsOf: url)
    }

    func remove(itemID: UUID) throws {
        let folder = root.appendingPathComponent(itemID.uuidString, isDirectory: true)
        try FileManager.default.removeItem(at: folder)
    }

    var pendingCount: Int {
        ((try? FileManager.default.contentsOfDirectory(at: root, includingPropertiesForKeys: nil))
         ?? []).count
    }
}
