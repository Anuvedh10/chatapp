import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import 'users_screen.dart';

class RegisterScreen extends StatefulWidget {
  const RegisterScreen({super.key});

  @override
  State<RegisterScreen> createState() => _RegisterScreenState();
}

class _RegisterScreenState extends State<RegisterScreen> {
  final emailController = TextEditingController();
  final otpController = TextEditingController();
  final usernameController = TextEditingController();
  final passwordController = TextEditingController();
  final FirebaseAuth _auth = FirebaseAuth.instance;
  final String serverUrl = "https://chatapp-1tcs.onrender.com";

  int _step = 0;
  bool isLoading = false;

  // ── Step 1: Send OTP ──────────────────────────────────────────────────────
  Future<void> sendOtpViaServer() async {
    final email = emailController.text.trim();
    if (email.isEmpty || !email.contains('@')) {
      _showSnack("Enter a valid Gmail address");
      return;
    }

    setState(() => isLoading = true);
    try {
      final response = await http.post(
        Uri.parse("$serverUrl/send-otp"),
        headers: {"Content-Type": "application/json"},
        body: jsonEncode({"email": email}),
      );

      if (response.statusCode == 200) {
        _showSnack("OTP sent to $email ✓");
        setState(() => _step = 1);
      } else {
        final body = jsonDecode(response.body);
        _showSnack(body['detail'] ?? "Failed to send OTP");
      }
    } catch (e) {
      _showSnack("Connection error. Check internet.");
    } finally {
      if (mounted) setState(() => isLoading = false);
    }
  }

  // ── Step 2: Verify OTP ────────────────────────────────────────────────────
  Future<void> verifyOtp() async {
    final otp = otpController.text.trim();
    if (otp.length != 6) {
      _showSnack("Enter the 6-digit OTP");
      return;
    }

    setState(() => isLoading = true);
    try {
      final response = await http.post(
        Uri.parse("$serverUrl/verify-otp"),
        headers: {"Content-Type": "application/json"},
        body: jsonEncode({
          "email": emailController.text.trim(),
          "otp": otp,
        }),
      );

      if (response.statusCode == 200) {
        _showSnack("Email verified ✓");
        setState(() => _step = 2);
      } else {
        final body = jsonDecode(response.body);
        _showSnack(body['detail'] ?? "Invalid OTP. Try again.");
      }
    } catch (e) {
      _showSnack("Connection error. Check internet.");
    } finally {
      if (mounted) setState(() => isLoading = false);
    }
  }

  // ── Step 3: Create Account ────────────────────────────────────────────────
  Future<void> createAccount() async {
    final username = usernameController.text.trim();
    final password = passwordController.text;
    final email = emailController.text.trim();

    if (username.isEmpty) {
      _showSnack("Enter a username");
      return;
    }
    if (password.length < 6) {
      _showSnack("Password must be at least 6 characters");
      return;
    }

    setState(() => isLoading = true);
    try {
      // 1. Register on your server
      final response = await http.post(
        Uri.parse("$serverUrl/register"),
        headers: {"Content-Type": "application/json"},
        body: jsonEncode({
          "username": username,
          "password": password,
          "email": email,
        }),
      );

      if (!mounted) return;

      if (response.statusCode == 200 || response.statusCode == 201) {
        // 2. Create Firebase account for cross-device login
        try {
          await _auth.createUserWithEmailAndPassword(
            email: email,
            password: password,
          );
          await _auth.currentUser?.updateDisplayName(username);
        } on FirebaseAuthException catch (e) {
          // If Firebase account already exists, just sign in
          if (e.code == 'email-already-in-use') {
            await _auth.signInWithEmailAndPassword(
              email: email,
              password: password,
            );
          }
          // Other Firebase errors are non-blocking — continue anyway
        }

        // 3. Save username locally
        final prefs = await SharedPreferences.getInstance();
        await prefs.setString('username', username);

        if (!mounted) return;
        Navigator.pushReplacement(
          context,
          MaterialPageRoute(
            builder: (_) => UsersScreen(currentUser: username),
          ),
        );
      } else {
        final body = jsonDecode(response.body);
        _showSnack(body['detail'] ?? "Registration failed");
      }
    } on FirebaseAuthException catch (e) {
      _showSnack("Firebase error: ${e.message}");
    } catch (e) {
      _showSnack("Connection error. Check internet.");
    } finally {
      if (mounted) setState(() => isLoading = false);
    }
  }

  void _showSnack(String msg) {
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(msg)));
  }

  // ── UI ────────────────────────────────────────────────────────────────────
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFF5F5F5),
      appBar: AppBar(
        title: const Text("Create Account"),
        backgroundColor: const Color(0xFF1A1A2E),
        foregroundColor: Colors.white,
      ),
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              _buildStepIndicator(),
              const SizedBox(height: 32),

              // ── Step 0: Enter Gmail ────────────────────────────────────
              if (_step == 0) ...[
                const Text(
                  "Enter your Gmail",
                  style: TextStyle(fontSize: 22, fontWeight: FontWeight.w600),
                ),
                const SizedBox(height: 6),
                const Text(
                  "We'll send a 6-digit verification code to your Gmail.",
                  style: TextStyle(color: Colors.black54),
                ),
                const SizedBox(height: 24),
                _buildField(
                  emailController,
                  "Gmail address",
                  Icons.email_outlined,
                  inputType: TextInputType.emailAddress,
                ),
                const SizedBox(height: 20),
                _buildPrimaryButton(
                  "Send OTP",
                  isLoading ? null : sendOtpViaServer,
                ),
              ],

              // ── Step 1: Verify OTP ─────────────────────────────────────
              if (_step == 1) ...[
                const Text(
                  "Verify OTP",
                  style: TextStyle(fontSize: 22, fontWeight: FontWeight.w600),
                ),
                const SizedBox(height: 6),
                Text(
                  "Enter the 6-digit code sent to ${emailController.text.trim()}",
                  style: const TextStyle(color: Colors.black54),
                ),
                const SizedBox(height: 24),
                _buildField(
                  otpController,
                  "6-digit OTP",
                  Icons.pin_outlined,
                  inputType: TextInputType.number,
                  maxLength: 6,
                ),
                const SizedBox(height: 4),
                Align(
                  alignment: Alignment.centerRight,
                  child: TextButton(
                    onPressed: isLoading ? null : sendOtpViaServer,
                    child: const Text(
                      "Resend OTP",
                      style: TextStyle(color: Color(0xFF1A1A2E)),
                    ),
                  ),
                ),
                const SizedBox(height: 8),
                _buildPrimaryButton(
                  "Verify OTP",
                  isLoading ? null : verifyOtp,
                ),
              ],

              // ── Step 2: Username + Password ────────────────────────────
              if (_step == 2) ...[
                const Text(
                  "Set up your account",
                  style: TextStyle(fontSize: 22, fontWeight: FontWeight.w600),
                ),
                const SizedBox(height: 6),
                const Text(
                  "Choose a username and password to log in on any device.",
                  style: TextStyle(color: Colors.black54),
                ),
                const SizedBox(height: 24),
                _buildField(
                  usernameController,
                  "Username",
                  Icons.person_outline,
                ),
                const SizedBox(height: 14),
                _buildField(
                  passwordController,
                  "Password (min 6 characters)",
                  Icons.lock_outline,
                  obscure: true,
                ),
                const SizedBox(height: 24),
                _buildPrimaryButton(
                  "Create Account",
                  isLoading ? null : createAccount,
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }

  // ── Step Indicator ────────────────────────────────────────────────────────
  Widget _buildStepIndicator() {
    const steps = ["Gmail", "OTP", "Profile"];
    return Row(
      children: List.generate(steps.length, (i) {
        final isActive = i == _step;
        final isDone = i < _step;
        return Expanded(
          child: Row(
            children: [
              Expanded(
                child: Column(
                  children: [
                    CircleAvatar(
                      radius: 18,
                      backgroundColor: isDone
                          ? Colors.green
                          : isActive
                              ? const Color(0xFF1A1A2E)
                              : Colors.grey.shade300,
                      child: isDone
                          ? const Icon(Icons.check,
                              color: Colors.white, size: 16)
                          : Text(
                              "${i + 1}",
                              style: TextStyle(
                                color: isActive
                                    ? Colors.white
                                    : Colors.grey.shade600,
                                fontSize: 13,
                                fontWeight: FontWeight.bold,
                              ),
                            ),
                    ),
                    const SizedBox(height: 5),
                    Text(
                      steps[i],
                      style: TextStyle(
                        fontSize: 11,
                        color: isActive
                            ? const Color(0xFF1A1A2E)
                            : Colors.grey.shade500,
                        fontWeight:
                            isActive ? FontWeight.w600 : FontWeight.normal,
                      ),
                    ),
                  ],
                ),
              ),
              if (i < steps.length - 1)
                Expanded(
                  child: Divider(
                    color: isDone ? Colors.green : Colors.grey.shade300,
                    thickness: 2,
                  ),
                ),
            ],
          ),
        );
      }),
    );
  }

  // ── Reusable Widgets ──────────────────────────────────────────────────────
  Widget _buildPrimaryButton(String label, VoidCallback? onPressed) {
    return ElevatedButton(
      onPressed: onPressed,
      style: ElevatedButton.styleFrom(
        backgroundColor: const Color(0xFF1A1A2E),
        foregroundColor: Colors.white,
        padding: const EdgeInsets.symmetric(vertical: 16),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(12),
        ),
      ),
      child: isLoading
          ? const SizedBox(
              height: 20,
              width: 20,
              child: CircularProgressIndicator(
                color: Colors.white,
                strokeWidth: 2,
              ),
            )
          : Text(label, style: const TextStyle(fontSize: 16)),
    );
  }

  Widget _buildField(
    TextEditingController ctrl,
    String label,
    IconData icon, {
    bool obscure = false,
    TextInputType inputType = TextInputType.text,
    int? maxLength,
  }) {
    return TextField(
      controller: ctrl,
      obscureText: obscure,
      keyboardType: inputType,
      maxLength: maxLength,
      decoration: InputDecoration(
        labelText: label,
        prefixIcon: Icon(icon, size: 20),
        filled: true,
        fillColor: Colors.white,
        counterText: '',
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: BorderSide.none,
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: const BorderSide(color: Color(0xFFE0E0E0)),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: const BorderSide(color: Color(0xFF1A1A2E)),
        ),
      ),
    );
  }
}
