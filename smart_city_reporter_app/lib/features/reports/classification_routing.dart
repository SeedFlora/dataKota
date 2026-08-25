import 'report_models.dart';

class AgencyRecommendation {
  const AgencyRecommendation({
    required this.name,
    required this.role,
    required this.priorityLabel,
  });

  final String name;
  final String role;
  final String priorityLabel;
}

class ClassificationRoutingGuidance {
  const ClassificationRoutingGuidance({
    required this.category,
    required this.summary,
    required this.routingReason,
    required this.agencies,
    this.reviewNote,
    this.isUncertain = false,
  });

  final IssueCategory category;
  final String summary;
  final String routingReason;
  final List<AgencyRecommendation> agencies;
  final String? reviewNote;
  final bool isUncertain;

  String get operationalLabel => category.label;
  IssueCategory get baseCategory => category;
}

ClassificationRoutingGuidance buildRoutingGuidanceFromPrediction(
  AiPrediction prediction, {
  IssueCategory? selectedCategory,
}) {
  return _guidanceFor(selectedCategory ?? prediction.category);
}

ClassificationRoutingGuidance buildClassificationRoutingGuidance({
  required IssueCategory category,
}) {
  return _guidanceFor(category);
}

ClassificationRoutingGuidance _guidanceFor(IssueCategory category) {
  return switch (category) {
    IssueCategory.dinasBinaMarga => _binaMargaGuidance,
    IssueCategory.satpolPP => _satpolGuidance,
    IssueCategory.dinasPerhubungan => _dishubGuidance,
    IssueCategory.kelurahan => _kelurahanGuidance,
    IssueCategory.dinasPertamananHutan => _pertamananGuidance,
    IssueCategory.dinasSDA => _sdaGuidance,
    IssueCategory.dinasCiptaKarya => _ciptaKaryaGuidance,
    IssueCategory.badanBUMD => _bumdGuidance,
    IssueCategory.instansiLain => _instansiLainGuidance,
  };
}

const _binaMargaGuidance = ClassificationRoutingGuidance(
  category: IssueCategory.dinasBinaMarga,
  summary:
      'Kerusakan jalan, lubang, trotoar rusak, dan jalan ambles dirutekan ke Dinas Bina Marga.',
  routingReason:
      'Bina Marga menangani perawatan dan perbaikan permukaan jalan provinsi/kota. Untuk gangguan arus lalu lintas yang menyertai, Dishub bisa menjadi pendukung.',
  agencies: [
    AgencyRecommendation(
      name: 'Dinas Bina Marga',
      role:
          'Rute utama untuk lubang jalan, kerusakan permukaan, trotoar, dan jalan ambles.',
      priorityLabel: 'Utama',
    ),
    AgencyRecommendation(
      name: 'Dinas Perhubungan',
      role:
          'Pendukung bila kerusakan menghambat arus lalu lintas atau butuh rambu sementara.',
      priorityLabel: 'Pendukung',
    ),
  ],
);

const _satpolGuidance = ClassificationRoutingGuidance(
  category: IssueCategory.satpolPP,
  summary:
      'PKL liar, reklame liar, vandalisme, dan pelanggaran ketertiban umum dirutekan ke Satpol PP.',
  routingReason:
      'Satpol PP berwenang melakukan penertiban dan pembinaan terkait ketertiban umum di ruang publik.',
  agencies: [
    AgencyRecommendation(
      name: 'Satuan Polisi Pamong Praja',
      role:
          'Rute utama untuk penertiban PKL liar, reklame, vandalisme, dan pelanggaran ketertiban.',
      priorityLabel: 'Utama',
    ),
  ],
);

const _dishubGuidance = ClassificationRoutingGuidance(
  category: IssueCategory.dinasPerhubungan,
  summary:
      'Lampu lalu lintas, rambu, parkir liar, halte, dan hambatan arus lalu lintas dirutekan ke Dinas Perhubungan.',
  routingReason:
      'Dishub mengelola perlengkapan jalan, parkir, dan sarana transportasi publik.',
  agencies: [
    AgencyRecommendation(
      name: 'Dinas Perhubungan',
      role:
          'Rute utama untuk rambu rusak, parkir liar, lampu lalu lintas, halte, dan hambatan arus.',
      priorityLabel: 'Utama',
    ),
  ],
  reviewNote:
      'Untuk kecelakaan aktif atau bahaya langsung, hubungi layanan darurat lebih dulu sebelum menunggu moderasi aplikasi.',
);

const _kelurahanGuidance = ClassificationRoutingGuidance(
  category: IssueCategory.kelurahan,
  summary:
      'Sampah lingkungan permukiman, kebersihan RT/RW, dan isu warga lokal dirutekan ke kelurahan setempat.',
  routingReason:
      'Banyak isu lingkungan kecil ditangani lebih cepat lewat kelurahan dan PPSU dibanding eskalasi langsung ke dinas.',
  agencies: [
    AgencyRecommendation(
      name: 'Kelurahan',
      role:
          'Rute utama untuk sampah lingkungan, kebersihan permukiman, dan isu warga lokal.',
      priorityLabel: 'Utama',
    ),
  ],
);

const _pertamananGuidance = ClassificationRoutingGuidance(
  category: IssueCategory.dinasPertamananHutan,
  summary:
      'Pohon tumbang, pohon mati, perawatan taman, dan satwa liar di ruang publik dirutekan ke Dinas Pertamanan dan Hutan Kota.',
  routingReason:
      'Dinas Pertamanan menangani pemangkasan, pengangkutan, dan evaluasi pohon serta perawatan taman kota.',
  agencies: [
    AgencyRecommendation(
      name: 'Dinas Pertamanan dan Hutan',
      role: 'Rute utama untuk pohon dan taman publik.',
      priorityLabel: 'Utama',
    ),
  ],
  reviewNote:
      'Bila pohon tumbang menutup jalan atau menimpa aset/orang, eskalasi cepat ke layanan darurat tetap diperlukan.',
);

const _sdaGuidance = ClassificationRoutingGuidance(
  category: IssueCategory.dinasSDA,
  summary:
      'Banjir, saluran air mampet, kali-sungai, dan tutup saluran rusak dirutekan ke Dinas Sumber Daya Air.',
  routingReason:
      'Dinas SDA mengelola drainase makro, kali, sungai, dan pompa air kota.',
  agencies: [
    AgencyRecommendation(
      name: 'Dinas Sumber Daya Air',
      role:
          'Rute utama untuk banjir, saluran air, kali-sungai, dan tutup saluran rusak.',
      priorityLabel: 'Utama',
    ),
  ],
);

const _ciptaKaryaGuidance = ClassificationRoutingGuidance(
  category: IssueCategory.dinasCiptaKarya,
  summary:
      'Tata ruang, bangunan publik, JPO/jembatan, RPTRA, rusun, dan fasilitas gedung pemda dirutekan ke Dinas Cipta Karya, Tata Ruang, dan Pertanahan.',
  routingReason:
      'Cipta Karya menangani aset bangunan publik dan tata ruang. Bina Marga tetap menjadi pendukung untuk akses jalan ke fasilitas.',
  agencies: [
    AgencyRecommendation(
      name: 'Dinas Cipta Karya, Tata Ruang, dan Pertanahan',
      role:
          'Rute utama untuk tata ruang, jembatan/JPO, fasilitas pemda, RPTRA, rusun.',
      priorityLabel: 'Utama',
    ),
  ],
);

const _bumdGuidance = ClassificationRoutingGuidance(
  category: IssueCategory.badanBUMD,
  summary:
      'Layanan yang dijalankan BUMD (PAM, Transjakarta, dan sejenis) dirutekan ke Badan Pembinaan BUMD.',
  routingReason:
      'BPBUMD mengoordinasikan keluhan terhadap layanan BUMD yang tidak menjadi tanggung jawab dinas teknis.',
  agencies: [
    AgencyRecommendation(
      name: 'Badan Pembinaan Badan Usaha Milik Daerah',
      role:
          'Rute utama untuk keluhan layanan BUMD (air bersih, transportasi publik, dsb.).',
      priorityLabel: 'Utama',
    ),
  ],
);

const _instansiLainGuidance = ClassificationRoutingGuidance(
  category: IssueCategory.instansiLain,
  summary: 'AI tidak yakin instansi mana yang paling tepat untuk laporan ini.',
  routingReason:
      'Foto atau deskripsi belum cukup spesifik untuk dipetakan ke salah satu 8 instansi utama. Perbaiki deskripsi atau pilih kategori manual sebelum submit.',
  agencies: [
    AgencyRecommendation(
      name: 'Instansi Lain',
      role: 'Akan ditinjau manual oleh moderator.',
      priorityLabel: 'Review Manual',
    ),
  ],
  reviewNote:
      'Perjelas deskripsi (contoh: "lubang besar di Jl. Sudirman dekat lampu merah") atau pilih kategori manual di atas. Jika benar-benar tidak masuk 8 instansi utama, biarkan di Instansi Lain.',
  isUncertain: true,
);
