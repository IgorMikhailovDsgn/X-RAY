import Foundation

/// Конвертация координат разметки из `docs/brainscan_annotation_mode.md`.
///
/// Три системы:
/// - **logical** — точки, как видит врач (UI плашки координат);
/// - **physical** — реальные пиксели скриншота (×`dpi` монитора), хранятся в БД;
/// - **crop** — внутри вырезанного региона (для `tumor_annotations.bbox`).
///
/// Region хранится в physical-координатах оригинала, Tumor — в координатах crop'а.
enum CoordinateConverter {
    /// logical → physical: умножение на dpi_scale_factor монитора (2.0 для Retina).
    static func physical(_ logical: CGRect, dpi: CGFloat) -> CGRect {
        CGRect(
            x: logical.origin.x * dpi,
            y: logical.origin.y * dpi,
            width: logical.width * dpi,
            height: logical.height * dpi
        )
    }

    /// Tumor в системе crop'а: physical-глобальные координаты опухоли минус
    /// physical-origin региона. Размеры остаются как у physical-опухоли.
    static func tumorInCrop(tumorLogical: CGRect, regionLogical: CGRect, dpi: CGFloat) -> CGRect {
        let pt = physical(tumorLogical, dpi: dpi)
        let pr = physical(regionLogical, dpi: dpi)
        return CGRect(
            x: pt.origin.x - pr.origin.x,
            y: pt.origin.y - pr.origin.y,
            width: pt.width,
            height: pt.height
        )
    }
}
