import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:flutter_map_dragmarker/flutter_map_dragmarker.dart';
import 'package:latlong2/latlong.dart';

import '../../app/theme/app_theme.dart';
import '../../features/reports/report_models.dart';

class ReportMapView extends StatelessWidget {
  const ReportMapView({
    super.key,
    required this.center,
    this.zoom = 13.5,
    this.height = 260,
    this.reports = const [],
    this.selectedLocation,
    this.onLocationChanged,
    this.onReportTap,
    this.showCompassHint = false,
    this.expand = false,
  });

  final LatLng center;
  final double zoom;
  final double height;
  final List<CityReport> reports;
  final ReportLocationData? selectedLocation;
  final ValueChanged<LatLng>? onLocationChanged;
  final ValueChanged<CityReport>? onReportTap;
  final bool showCompassHint;

  /// When true, the map fills its parent and skips the rounded card chrome.
  /// Use for full-bleed map screens where another layer draws the surround.
  final bool expand;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    final selectedLatLng = selectedLocation == null
        ? null
        : LatLng(selectedLocation!.latitude, selectedLocation!.longitude);

    final mapStack = Stack(
      children: [
        FlutterMap(
          options: MapOptions(
            initialCenter: selectedLatLng ?? center,
            initialZoom: zoom,
            interactionOptions: const InteractionOptions(
              flags: InteractiveFlag.all,
            ),
            onTap: onLocationChanged == null
                ? null
                : (_, latLng) => onLocationChanged!(latLng),
          ),
          children: [
            TileLayer(
              urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
              userAgentPackageName: 'com.smartcity.reporter',
            ),
            MarkerLayer(
              markers: reports
                  .map(
                    (report) => Marker(
                      point: LatLng(report.latitude, report.longitude),
                      width: 52,
                      height: 52,
                      child: GestureDetector(
                        onTap: onReportTap == null
                            ? null
                            : () => onReportTap!(report),
                        child: Icon(
                          Icons.location_on_rounded,
                          color: palette.danger,
                          size: 38,
                        ),
                      ),
                    ),
                  )
                  .toList(),
            ),
            if (selectedLatLng != null && onLocationChanged != null)
              DragMarkers(
                markers: [
                  DragMarker(
                    point: selectedLatLng,
                    size: const Size(68, 68),
                    offset: const Offset(0, -18),
                    builder: (_, _, isDragging) => Icon(
                      Icons.place_rounded,
                      color: isDragging
                          ? palette.accentCyan
                          : palette.accentBlue,
                      size: 50,
                    ),
                    onDragEnd: (_, latLng) => onLocationChanged!(latLng),
                  ),
                ],
              )
            else if (selectedLatLng != null)
              MarkerLayer(
                markers: [
                  Marker(
                    point: selectedLatLng,
                    width: 60,
                    height: 60,
                    child: Icon(
                      Icons.place_rounded,
                      color: palette.accentBlue,
                      size: 48,
                    ),
                  ),
                ],
              ),
            RichAttributionWidget(
              attributions: [
                TextSourceAttribution(
                  'OpenStreetMap contributors',
                  onTap: () {},
                ),
              ],
            ),
          ],
        ),
        if (showCompassHint)
          Positioned(
            left: 12,
            top: 12,
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              decoration: BoxDecoration(
                color: Colors.white.withValues(alpha: 0.94),
                borderRadius: BorderRadius.circular(999),
              ),
              child: const Text('Drag pin or tap map'),
            ),
          ),
      ],
    );

    if (expand) {
      return mapStack;
    }

    return Container(
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(24),
        border: Border.all(color: palette.border),
        boxShadow: const [
          BoxShadow(
            color: Color(0x120F172A),
            blurRadius: 20,
            offset: Offset(0, 10),
          ),
        ],
      ),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(24),
        child: SizedBox(height: height, child: mapStack),
      ),
    );
  }
}
