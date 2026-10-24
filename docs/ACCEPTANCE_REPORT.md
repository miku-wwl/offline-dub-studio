# Phase 2.5 acceptance report

Validation date: 2026-10-24, Pacific/Auckland. Baseline: `1b873652f9f608afb34f10d461c8ddfe156217f7`.

**OVERALL_STATUS=PARTIAL.** The actual supplied video completed the local Balanced pipeline and produced a verified MP4. Timing collisions, imperfect Chinese subtitle restoration, and subjective listening/video approval remain open. No full-length movie, GHCR publication, or GitHub release was attempted.

## Delivered engineering work

- Safe owned upload/import lifecycle: invalid inbox files survive, valid imports create stable independent snapshots, publication cannot overwrite existing media, and cleanup only removes app-owned unregistered files.
- Timestamped OCR regions and exact frame intervals; editable manual search regions; no inherited masks on absent frames or later scenes; lossless intermediate and no repair encoding when no subtitles are detected.
- Transcript/speaker approval before TTS, stable manual voice assignments, downstream retries with successful upstream stages retained, valid ASS/SRT and readable burn-in.
- Bounded timeline audio buffers, explicit speech overflow/collision/truncation diagnostics, OCR/repair cache provenance, per-attempt stage timing and cgroup peak memory.
- Patched `filelock==4.2.1`, installed-graph security auditing without ignored CVEs, and corrected CI container lifetime for production browser smoke checks.
- Fixed the production UI history-selection crash caused by treating a job summary as complete detail; regression uses the sparse API response.

## Real source and output

| Item | Measured result |
|---|---|
| Original | `test.webm`, 95.748 s, VP9 1920×1080 at 25 fps / Opus stereo 48 kHz |
| Original SHA-256 | `bb779354520eb5edd040910d970c41471235ad1f2b49e5d3d73abd3e9f1fc4d4` |
| Selected source interval | 10.000–70.000 s |
| Input clip | `data/inbox/test-60s.mp4`, exactly 60.000 s, H.264/AAC, same resolution/fps |
| Job | `e47f9f3b-7236-4afe-8548-f1295d497e43`, Balanced, `completed_with_warnings` |
| Providers | Faster-Whisper Small int8 CPU, Argos zh→en, Kokoro, Demucs htdemucs, OpenCV Balanced repair |
| Final MP4 | `D:/workshop/oct/offline-dub-studio/data/acceptance/phase-2.5/dubbed-60s.mp4` |
| Output size / SHA-256 | 18,261,468 bytes / `533dd7f1a0b14a65802907edc238b806f31d323f30ed103ccb7a9854abd1c58a` |
| Local media integrity | PASS: full decode, codecs, dimensions, fps, A/V duration, packet timestamps, matching API-download hash |
| Temporal safety | PASS: 459 inactive lossless-intermediate frames compared, zero changed |
| Audio measurements | 27 non-silent generated segments; zero mixed-PCM clipped samples; -22.0 LUFS, -3.8 dBFS final true peak |
| Timing | PARTIAL: 9 collisions >20 ms, maximum 1.085 s; no end tail loss |
| Subtitle repair | PARTIAL: missed glyphs and smearing remain visible |
| Assigned speakers | Three proposed manual groups with stable distinct voices; identities and automatic diarization are not verified |
| Subjective quality | PENDING_HUMAN_REVIEW |

The source file was preserved and kept out of Git. All models and generated media remain ignored. Required artifact collection reported no missing files. The detailed source command, failures, model workflow, full stage timings, performance limits and human checklist are in [REAL_VIDEO_ACCEPTANCE.md](REAL_VIDEO_ACCEPTANCE.md).

## Verification and delivery

Exact commands and test coverage are in [testing.md](testing.md). Machine-readable reports and logs live under ignored `data/acceptance/phase-2.5/`. A separate generated two-second fixture exercised queued cancel/resume/cancel without running model stages or changing its source. Recovery regression tests cover interrupted stages and existing valid caches. The production browser check verifies muted playback of the real private output; it cannot count as listening.

Dependency audit finds no known vulnerabilities among auditable installed packages and upstream CPU PyTorch versions. Argos 1.11.1's pinned upstream commit and the hash-pinned spaCy 3.8.0 model wheel are explicitly reported as unavailable to the PyPI audit. No CVE suppressions were added. MiniSBD remains an AGPL-3.0 transitive package; redistribution still requires the previously documented license/source review.

Repository: [miku-wwl/offline-dub-studio](https://github.com/miku-wwl/offline-dub-studio). Remote build/test evidence is the CI run for the final commit, linked in the delivery response and ignored `data/acceptance/phase-2.5/delivery.json`. [CI workflow history](https://github.com/miku-wwl/offline-dub-studio/actions/workflows/ci.yml). A local result alone does not assert GitHub Actions success.

## Acceptance boundary

Real provider execution and media integrity pass. English dub timing, manual speaker identity, cinematic background preservation, lip sync, translation/naturalness and visual reconstruction remain partial or pending human review. The 1,776.072 s processing figure sums all attempts, including rejected previews and cached retries; wall time including engineering/review was 4,326 s. The 338.660 s latest-entry sum includes caches and is not a fresh conversion benchmark. Peak observed cgroup memory was 2.527 GB; the 60-second lossless intermediate used 1.029 GB.

Open the final MP4 and listen to the source/stems/dub, then inspect all scenes. Native Windows Media Player playback is not claimed from FFmpeg or Chromium evidence. Two-hour acceptance remains blocked by the sample quality gate and unresolved sustained storage/memory/cancellation risks. No full film was started.
