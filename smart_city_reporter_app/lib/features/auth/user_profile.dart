import '../reports/report_models.dart';

class UserProfile {
  const UserProfile({
    required this.id,
    required this.fullName,
    required this.email,
    required this.phoneNumber,
    this.profilePhotoUrl,
    this.createdAt,
    this.updatedAt,
    this.isModerator = false,
    this.role = 'citizen',
    this.assignedAgency,
  });

  final String id;
  final String fullName;
  final String email;
  final String phoneNumber;
  final String? profilePhotoUrl;
  final DateTime? createdAt;
  final DateTime? updatedAt;
  final bool isModerator;
  final String role;
  final IssueCategory? assignedAgency;

  factory UserProfile.fromMap(Map<String, dynamic> map) {
    final moderatorValue = map['is_moderator'];
    final assignedAgencyValue = map['assigned_agency'];
    return UserProfile(
      id: map['id'] as String,
      fullName: map['full_name'] as String? ?? '',
      email: map['email'] as String? ?? '',
      phoneNumber: map['phone_number'] as String? ?? '',
      profilePhotoUrl: map['profile_photo_url'] as String?,
      createdAt: map['created_at'] == null
          ? null
          : DateTime.tryParse(map['created_at'] as String),
      updatedAt: map['updated_at'] == null
          ? null
          : DateTime.tryParse(map['updated_at'] as String),
      isModerator: moderatorValue is bool
          ? moderatorValue
          : moderatorValue == 1,
      role: map['role'] as String? ?? 'citizen',
      assignedAgency: assignedAgencyValue is String
          ? IssueCategory.fromValue(assignedAgencyValue)
          : null,
    );
  }

  Map<String, dynamic> toMap() {
    return {
      'id': id,
      'full_name': fullName,
      'email': email,
      'phone_number': phoneNumber,
      'profile_photo_url': profilePhotoUrl,
      'is_moderator': isModerator,
      'role': role,
      'assigned_agency': assignedAgency?.dbValue,
    };
  }

  UserProfile copyWith({
    String? fullName,
    String? email,
    String? phoneNumber,
    String? profilePhotoUrl,
    bool? isModerator,
    String? role,
    IssueCategory? assignedAgency,
  }) {
    return UserProfile(
      id: id,
      fullName: fullName ?? this.fullName,
      email: email ?? this.email,
      phoneNumber: phoneNumber ?? this.phoneNumber,
      profilePhotoUrl: profilePhotoUrl ?? this.profilePhotoUrl,
      createdAt: createdAt,
      updatedAt: updatedAt,
      isModerator: isModerator ?? this.isModerator,
      role: role ?? this.role,
      assignedAgency: assignedAgency ?? this.assignedAgency,
    );
  }
}
