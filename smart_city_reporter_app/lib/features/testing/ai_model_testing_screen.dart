import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';

import '../../core/config/app_config.dart';
import '../../core/services/ai_classification_service.dart';
import '../../core/services/cloud_classification_service.dart';
import '../../core/services/media_service.dart';
import '../../core/widgets/classification_routing_card.dart';
import '../../core/widgets/smart_city_ui.dart';
import '../reports/classification_routing.dart';
import '../reports/report_models.dart';

class AiModelTestingScreen extends ConsumerStatefulWidget {
  const AiModelTestingScreen({super.key});

  @override
  ConsumerState<AiModelTestingScreen> createState() =>
      _AiModelTestingScreenState();
}

class _AiModelTestingScreenState extends ConsumerState<AiModelTestingScreen> {
  final TextEditingController _laporanController = TextEditingController();
  XFile? _image;
  AiPrediction? _prediction;
  bool _busy = false;
  bool? _healthy;
  String? _error;

  @override
  void dispose() {
    _laporanController.dispose();
    super.dispose();
  }

  Future<void> _pickImage(Future<XFile?> Function() picker) async {
    final file = await picker();
    if (!mounted || file == null) {
      return;
    }
    setState(() {
      _image = file;
      _prediction = null;
      _error = null;
    });
  }

  Future<void> _checkHealth() async {
    setState(() => _busy = true);
    try {
      final ok = await ref
          .read(cloudClassificationServiceProvider)
          .healthCheck();
      if (!mounted) return;
      setState(() => _healthy = ok);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _classify() async {
    final image = _image;
    final laporan = _laporanController.text.trim();
    if (image == null) {
      setState(() => _error = 'Pilih foto dulu.');
      return;
    }
    if (laporan.length < 10) {
      setState(() => _error = 'Tulis deskripsi minimal 10 karakter.');
      return;
    }

    setState(() {
      _busy = true;
      _error = null;
    });

    try {
      final prediction = await ref
          .read(aiClassificationServiceProvider)
          .classify(
            imageFile: image,
            description: laporan,
            location: const ReportLocationData(
              latitude: -6.2088,
              longitude: 106.8456,
              address: 'Jakarta',
            ),
          );
      if (!mounted) return;
      setState(() => _prediction = prediction);
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final media = ref.read(mediaServiceProvider);
    final config = ref.watch(appConfigProvider);
    final theme = Theme.of(context);
    final routingGuidance = _prediction == null
        ? null
        : buildRoutingGuidanceFromPrediction(_prediction!);
    final topPredictions = _prediction?.topPredictions(limit: 5) ?? const [];

    return Scaffold(
      appBar: AppBar(title: const Text('Multimodal AI Testing')),
      body: SafeArea(
        child: ListView(
          padding: pagePadding(context),
          children: [
            GradientHeroHeader(
              title: 'Cloud multimodal classifier',
              subtitle: config.enableTestingMode
                  ? 'Testing mode aktif — memakai DemoAi (deterministik dari hash gambar+teks).'
                  : 'Mengirim gambar + deskripsi ke ${config.crmApiUrl}/predict.',
              trailing: const SmartCityLogo(size: 56),
            ),
            const SizedBox(height: 16),
            SectionCard(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const SectionHeader(
                    title: 'Status backend',
                    subtitle:
                        'Cek apakah inference server multimodal hidup dan dapat menerima request.',
                  ),
                  const SizedBox(height: 12),
                  Row(
                    children: [
                      ElevatedButton.icon(
                        onPressed: _busy ? null : _checkHealth,
                        icon: const Icon(Icons.health_and_safety_outlined),
                        label: const Text('Health check'),
                      ),
                      const SizedBox(width: 12),
                      if (_healthy != null)
                        Text(
                          _healthy! ? 'OK' : 'Tidak bisa terhubung',
                          style: theme.textTheme.bodyMedium?.copyWith(
                            color: _healthy! ? Colors.green : Colors.red,
                          ),
                        ),
                    ],
                  ),
                ],
              ),
            ),
            const SizedBox(height: 20),
            SectionCard(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const SectionHeader(
                    title: '1. Pilih foto',
                    subtitle: 'Dari kamera atau galeri.',
                  ),
                  const SizedBox(height: 16),
                  if (_image != null)
                    ClipRRect(
                      borderRadius: BorderRadius.circular(22),
                      child: Image.file(
                        File(_image!.path),
                        height: 240,
                        width: double.infinity,
                        fit: BoxFit.cover,
                      ),
                    )
                  else
                    Container(
                      height: 240,
                      decoration: BoxDecoration(
                        borderRadius: BorderRadius.circular(22),
                        color: const Color(0xFFE2E8F0),
                      ),
                      child: const Center(
                        child: Icon(
                          Icons.add_photo_alternate_outlined,
                          size: 52,
                        ),
                      ),
                    ),
                  const SizedBox(height: 16),
                  Row(
                    children: [
                      Expanded(
                        child: ElevatedButton.icon(
                          onPressed: _busy
                              ? null
                              : () => _pickImage(media.pickFromCamera),
                          icon: const Icon(Icons.photo_camera_outlined),
                          label: const Text('Kamera'),
                        ),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: OutlinedButton.icon(
                          onPressed: _busy
                              ? null
                              : () => _pickImage(media.pickFromGallery),
                          icon: const Icon(Icons.photo_library_outlined),
                          label: const Text('Galeri'),
                        ),
                      ),
                    ],
                  ),
                ],
              ),
            ),
            const SizedBox(height: 20),
            SectionCard(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const SectionHeader(
                    title: '2. Tulis deskripsi (laporan)',
                    subtitle:
                        'Model menerima teks + gambar bersamaan. Min. 10 karakter.',
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    controller: _laporanController,
                    minLines: 3,
                    maxLines: 5,
                    decoration: const InputDecoration(
                      hintText:
                          'Contoh: "Lubang besar di Jl. Sudirman dekat lampu merah."',
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 20),
            SectionCard(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const SectionHeader(
                    title: '3. Jalankan prediksi',
                    subtitle:
                        'Mengirim ke endpoint /predict. Mengembalikan kategori + skor model.',
                  ),
                  const SizedBox(height: 16),
                  ElevatedButton.icon(
                    onPressed: _busy ? null : _classify,
                    icon: _busy
                        ? const SizedBox(
                            width: 20,
                            height: 20,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Icon(Icons.auto_awesome_outlined),
                    label: const Text('Classify'),
                  ),
                ],
              ),
            ),
            if (_prediction != null) ...[
              const SizedBox(height: 20),
              SectionCard(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const SectionHeader(
                      title: 'Hasil',
                      subtitle:
                          'Kategori dengan skor model teratas (belum terkalibrasi).',
                    ),
                    const SizedBox(height: 16),
                    Container(
                      padding: const EdgeInsets.all(16),
                      decoration: BoxDecoration(
                        borderRadius: BorderRadius.circular(20),
                        color: const Color(0xFFE0F2FE),
                      ),
                      child: Row(
                        children: [
                          const Icon(Icons.analytics_outlined),
                          const SizedBox(width: 12),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  _prediction!.category.label,
                                  style: theme.textTheme.titleMedium,
                                ),
                                const SizedBox(height: 4),
                                Text(
                                  'Skor model ${(_prediction!.confidence * 100).toStringAsFixed(1)}%',
                                  style: theme.textTheme.bodyMedium,
                                ),
                              ],
                            ),
                          ),
                        ],
                      ),
                    ),
                    if (topPredictions.isNotEmpty) ...[
                      const SizedBox(height: 16),
                      Text('Top kandidat', style: theme.textTheme.titleSmall),
                      const SizedBox(height: 10),
                      ...topPredictions.map((entry) {
                        return Padding(
                          padding: const EdgeInsets.only(bottom: 10),
                          child: Row(
                            children: [
                              Expanded(child: Text(entry.category.label)),
                              Text(
                                '${(entry.confidence * 100).toStringAsFixed(1)}%',
                              ),
                            ],
                          ),
                        );
                      }),
                    ],
                  ],
                ),
              ),
              const SizedBox(height: 20),
              ClassificationRoutingCard(
                guidance: routingGuidance!,
                title: 'Rute pelaporan',
                subtitle:
                    'Rekomendasi instansi tujuan berdasarkan prediksi multimodal.',
              ),
            ],
            if (_error != null) ...[
              const SizedBox(height: 20),
              SectionCard(
                child: Text(
                  _error!,
                  style: TextStyle(color: theme.colorScheme.error),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
