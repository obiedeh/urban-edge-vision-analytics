import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Camera, type InferenceResult, type Point, type RuntimeCameraStatus } from "@/lib/api";
import { DetectionOverlay } from "@/components/detection-overlay";
import { CameraStateChip } from "@/components/status-chip";
import { cn, formatMs, formatSeconds } from "@/lib/utils";
import { AlertTriangle, BrainCircuit, Video, VideoOff, Loader2, WifiOff, SwitchCamera, Lock } from "lucide-react";

const STALE_RESULT_S = 8;
const HTTPS_PORT = 8443;

/** Phones and tablets: offer front/back instead of a device list. */
const IS_MOBILE = typeof navigator !== "undefined" && /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent);

/** Why the browser refuses camera access here, and the URL that fixes it. */
export function insecureContextMessage(): string {
  const host = window.location.hostname;
  return `Camera access needs a secure context. Open this console over HTTPS at https://${host}:${HTTPS_PORT}/ (opt-in TLS front door, see the README section "Browser camera from another device"), or on the device itself at http://localhost:8080/.`;
}

interface Props {
  camera: Camera;
  result: InferenceResult | null;
  runtime: RuntimeCameraStatus | null;
  className?: string;
  /** When false the overlay/status strips are hidden (thumbnail mode). */
  showOverlay?: boolean;
  /** Cap server frame rate for thumbnails. */
  maxFps?: number;
  /** saved vehicle_count line (normalized A→B) drawn on the overlay */
  countLine?: Point[] | null;
}

/** Measure the rendered size of the video box so the SVG overlay can scale normalized boxes. */
function useBoxSize<T extends HTMLElement>() {
  const ref = useRef<T | null>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const r = entries[0]?.contentRect;
      if (r) setSize({ width: r.width, height: r.height });
    });
    ro.observe(el);
    setSize({ width: el.clientWidth, height: el.clientHeight });
    return () => ro.disconnect();
  }, []);
  return { ref, size };
}

/**
 * One camera's live view: MJPEG <img> (or the operator's local webcam for
 * browser_webrtc cameras) with the SSE detection overlay drawn on top.
 * The video is never hidden by inference state — inference problems are shown
 * as banners over the still-playing stream.
 */
export function LiveVideo({ camera, result, runtime, className, showOverlay = true, maxFps, countLine }: Props) {
  const { ref: boxRef, size } = useBoxSize<HTMLDivElement>();
  const [intrinsic, setIntrinsic] = useState<{ width: number; height: number } | null>(null);
  const [imgError, setImgError] = useState(false);
  const [streamKey, setStreamKey] = useState(0);
  const isWebcam = camera.profile === "browser_webrtc";

  // Reconnect the MJPEG stream when the camera (re)starts after an error.
  const state = runtime?.state ?? camera.runtime?.state ?? null;
  useEffect(() => {
    if (imgError && (state === "streaming" || state === "starting" || state === "connecting")) {
      const t = setTimeout(() => { setImgError(false); setStreamKey((k) => k + 1); }, 2000);
      return () => clearTimeout(t);
    }
  }, [imgError, state]);

  useEffect(() => { setImgError(false); setStreamKey((k) => k + 1); setIntrinsic(null); }, [camera.id]);

  // ── WebRTC (browser webcam) ──────────────────────────────────────────────
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const peerRef = useRef<RTCPeerConnection | null>(null);
  const mediaRef = useRef<MediaStream | null>(null);
  const sessionRef = useRef<string | null>(null);
  const [rtc, setRtc] = useState<"idle" | "connecting" | "live" | "error">("idle");
  const [rtcError, setRtcError] = useState<string | null>(null);
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [deviceId, setDeviceId] = useState<string>("");
  const [facing, setFacing] = useState<"user" | "environment">("environment");
  const secure = typeof window !== "undefined" ? window.isSecureContext : true;

  /** List video inputs; labels are only filled in once the page has camera permission. */
  const loadDevices = useCallback(async () => {
    if (!navigator.mediaDevices?.enumerateDevices) return;
    try {
      const all = await navigator.mediaDevices.enumerateDevices();
      setDevices(all.filter((d) => d.kind === "videoinput"));
    } catch { /* permission not granted yet */ }
  }, []);
  useEffect(() => { if (isWebcam && secure) void loadDevices(); }, [isWebcam, secure, loadDevices]);

  const stopWebcam = useCallback(async () => {
    peerRef.current?.close();
    peerRef.current = null;
    mediaRef.current?.getTracks().forEach((t) => t.stop());
    mediaRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
    const sid = sessionRef.current;
    sessionRef.current = null;
    if (sid) await api.webrtc.close(sid).catch(() => null);
    setRtc("idle");
  }, []);

  async function shareWebcam(pick?: { deviceId?: string; facing?: "user" | "environment" }) {
    setRtcError(null);
    if (!window.isSecureContext) {
      setRtc("error"); setRtcError(insecureContextMessage()); return;
    }
    if (!navigator.mediaDevices?.getUserMedia || !window.RTCPeerConnection) {
      setRtc("error"); setRtcError("This browser does not expose WebRTC camera APIs."); return;
    }
    const chosenId = pick?.deviceId ?? deviceId;
    const chosenFacing = pick?.facing ?? facing;
    try {
      setRtc("connecting");
      await stopWebcam();
      setRtc("connecting");
      const video: MediaTrackConstraints = { width: { ideal: 1280 }, height: { ideal: 720 }, frameRate: { ideal: 30 } };
      if (chosenId) video.deviceId = { exact: chosenId };
      else if (IS_MOBILE) video.facingMode = { ideal: chosenFacing };
      const stream = await navigator.mediaDevices.getUserMedia({ video, audio: false });
      mediaRef.current = stream;
      void loadDevices(); // labels become available once permission is granted
      if (videoRef.current) videoRef.current.srcObject = stream;
      const peer = new RTCPeerConnection({ iceServers: [{ urls: "stun:stun.l.google.com:19302" }] });
      peerRef.current = peer;
      stream.getTracks().forEach((t) => peer.addTrack(t, stream));
      const offer = await peer.createOffer();
      await peer.setLocalDescription(offer);
      const answer = await api.webrtc.offer({ sdp: offer.sdp ?? "", type: offer.type, camera_id: camera.id });
      sessionRef.current = answer.session_id;
      await peer.setRemoteDescription({ sdp: answer.sdp, type: answer.type });
      peer.onconnectionstatechange = () => {
        if (peer.connectionState === "failed" || peer.connectionState === "disconnected") {
          setRtc("error"); setRtcError(`Peer connection ${peer.connectionState}.`);
        }
      };
      setRtc("live");
    } catch (e) {
      setRtc("error");
      setRtcError(e instanceof Error ? e.message : "Webcam share failed.");
      await stopWebcam().catch(() => null);
      setRtc("error");
    }
  }

  useEffect(() => () => { void stopWebcam(); }, [camera.id, stopWebcam]);

  // ── Derived inference state ─────────────────────────────────────────────
  const meta = result?.metadata;
  const infStatus = meta?.status ?? null;
  const resultAgeS = result ? Math.max(0, (Date.now() - result.timestamp_ms) / 1000) : null;
  const stale = resultAgeS !== null && resultAgeS > STALE_RESULT_S;
  const detections = infStatus === "ok" ? meta?.detections ?? [] : [];
  const packEvents = meta?.pack_events ?? [];
  const camError = state === "error" ? (runtime?.last_error ?? camera.runtime?.last_error ?? null) : null;

  return (
    <div className={cn("relative bg-black w-full aspect-video overflow-hidden", className)} ref={boxRef}>
      {isWebcam ? (
        <video
          ref={videoRef}
          autoPlay
          muted
          playsInline
          className="absolute inset-0 w-full h-full object-contain"
          onLoadedMetadata={(e) => {
            const v = e.currentTarget;
            if (v.videoWidth && v.videoHeight) setIntrinsic({ width: v.videoWidth, height: v.videoHeight });
          }}
        />
      ) : (
        <img
          key={streamKey}
          src={api.stream.mjpegUrl(camera.id, maxFps)}
          alt={`Live: ${camera.name}`}
          className="absolute inset-0 w-full h-full object-contain"
          onLoad={(e) => {
            const im = e.currentTarget;
            // Some browsers fire load per MJPEG part: only update state when the size actually changes.
            if (im.naturalWidth && im.naturalHeight) {
              setIntrinsic((prev) => (prev && prev.width === im.naturalWidth && prev.height === im.naturalHeight ? prev : { width: im.naturalWidth, height: im.naturalHeight }));
            }
            setImgError(false);
          }}
          onError={() => setImgError(true)}
        />
      )}

      {showOverlay && size.width > 0 && (
        <DetectionOverlay
          detections={detections}
          packEvents={packEvents}
          width={size.width}
          height={size.height}
          intrinsic={intrinsic}
          stale={stale}
          countLine={countLine}
        />
      )}

      {/* Browser camera controls — only for browser_webrtc cameras */}
      {isWebcam && rtc !== "live" && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 text-muted-foreground bg-black/60 px-4">
          {!secure ? (
            <div className="max-w-md rounded border border-yellow-500/40 bg-yellow-950/80 px-3 py-2 text-[11px] text-yellow-200 flex items-start gap-2">
              <Lock className="h-3.5 w-3.5 mt-0.5 shrink-0" />
              <span>{insecureContextMessage()}</span>
            </div>
          ) : rtc === "connecting" ? (
            <span className="flex items-center gap-2 text-xs"><Loader2 className="h-4 w-4 animate-spin" /> Connecting…</span>
          ) : (
            <>
              {IS_MOBILE ? (
                <div className="flex items-center gap-2 text-xs">
                  <button type="button" onClick={() => setFacing("user")} className={cn("rounded border px-2 py-1", facing === "user" ? "border-purple-400/60 text-purple-200 bg-purple-500/15" : "border-border text-muted-foreground")}>Front camera</button>
                  <button type="button" onClick={() => setFacing("environment")} className={cn("rounded border px-2 py-1", facing === "environment" ? "border-purple-400/60 text-purple-200 bg-purple-500/15" : "border-border text-muted-foreground")}>Back camera</button>
                </div>
              ) : devices.length > 0 && (
                <select
                  value={deviceId}
                  onChange={(e) => setDeviceId(e.target.value)}
                  className="rounded border border-border bg-background px-2 py-1 text-xs text-foreground max-w-xs"
                  aria-label="Camera"
                >
                  <option value="">Default camera</option>
                  {devices.map((d, i) => <option key={d.deviceId || i} value={d.deviceId}>{d.label || `Camera ${i + 1}`}</option>)}
                </select>
              )}
              <button
                type="button"
                onClick={() => void shareWebcam()}
                className="inline-flex items-center gap-2 rounded border border-purple-400/50 bg-purple-500/15 px-3 py-2 text-xs font-semibold text-purple-200 hover:bg-purple-500/25"
              >
                <Video className="h-3.5 w-3.5" /> Share camera
              </button>
            </>
          )}
          {rtcError && <span className="text-[10px] text-red-400 max-w-md text-center">{rtcError}</span>}
          {!rtcError && rtc === "idle" && secure && (
            <span className="text-[10px] text-muted-foreground/70 max-w-xs text-center">
              This browser's camera is sent to the server as this camera's feed. Inference overlays appear here.
              {!IS_MOBILE && devices.length > 0 && !devices[0].label ? " Camera names appear after the first share." : ""}
            </span>
          )}
        </div>
      )}
      {isWebcam && rtc === "live" && showOverlay && (
        <div className="absolute right-2 top-2 flex items-center gap-1">
          {IS_MOBILE ? (
            <button
              type="button"
              onClick={() => { const next = facing === "user" ? "environment" : "user"; setFacing(next); setDeviceId(""); void shareWebcam({ facing: next, deviceId: "" }); }}
              className="inline-flex items-center gap-1 rounded border border-border bg-black/70 px-2 py-1 text-[10px] text-foreground hover:border-purple-400/60"
              title="Switch between front and back camera"
            >
              <SwitchCamera className="h-3 w-3" /> Flip
            </button>
          ) : devices.length > 1 && (
            <select
              value={deviceId}
              onChange={(e) => { setDeviceId(e.target.value); void shareWebcam({ deviceId: e.target.value }); }}
              className="rounded border border-border bg-black/70 px-1.5 py-1 text-[10px] text-foreground max-w-[180px]"
              aria-label="Switch camera"
            >
              <option value="">Default camera</option>
              {devices.map((d, i) => <option key={d.deviceId || i} value={d.deviceId}>{d.label || `Camera ${i + 1}`}</option>)}
            </select>
          )}
          <button
            type="button"
            onClick={() => void stopWebcam()}
            className="inline-flex items-center gap-1 rounded border border-border bg-black/70 px-2 py-1 text-[10px] text-foreground hover:border-red-400/60"
          >
            <VideoOff className="h-3 w-3" /> Stop sharing
          </button>
        </div>
      )}

      {/* No-signal placeholder (video element stays mounted underneath) */}
      {!isWebcam && imgError && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-muted-foreground bg-black/70 pointer-events-none">
          <WifiOff className="h-6 w-6" />
          <span className="text-xs">
            {state === null || state === "stopped" ? "Camera not running" : state === "error" ? "Camera error" : "Waiting for frames…"}
          </span>
          {camError && <span className="text-[10px] text-red-400 max-w-md text-center px-4 break-words">{camError}</span>}
        </div>
      )}

      {showOverlay && (
        <>
          {/* top-left: camera state */}
          <div className="absolute left-2 top-2 flex items-center gap-1.5">
            <CameraStateChip state={state} />
            {runtime && state === "streaming" && (
              <span className="rounded bg-black/70 px-1.5 py-0.5 text-[10px] font-mono text-foreground/80 tabular-nums">
                {runtime.fps.toFixed(1)} fps{runtime.source_width ? ` · ${runtime.source_width}×${runtime.source_height}` : ""}{runtime.codec ? ` · ${runtime.codec}` : ""}
              </span>
            )}
          </div>

          {/* banners */}
          <div className="absolute inset-x-2 top-10 space-y-1 pointer-events-none">
            {infStatus === "inference_unavailable" && (
              <div className="flex items-center gap-2 rounded border border-red-500/50 bg-red-950/85 px-3 py-1.5 text-xs text-red-200">
                <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                <span className="font-semibold">Inference unavailable — video continues.</span>
                {meta?.model_error && <span className="truncate text-red-300/80">{meta.model_error}</span>}
              </div>
            )}
            {infStatus === "no_frame" && !imgError && (
              <div className="flex items-center gap-2 rounded border border-yellow-500/40 bg-yellow-950/80 px-3 py-1.5 text-xs text-yellow-200">
                <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                No frame for inference yet{meta?.camera_state ? ` (camera ${meta.camera_state})` : ""}.
              </div>
            )}
            {camError && !imgError && (
              <div className="flex items-center gap-2 rounded border border-red-500/50 bg-red-950/85 px-3 py-1.5 text-xs text-red-200 break-words">
                <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                <span>{camError}</span>
              </div>
            )}
          </div>

          {/* bottom: VLM summary */}
          <div className="absolute inset-x-2 bottom-2 rounded border border-border/70 bg-background/85 px-3 py-2 backdrop-blur pointer-events-none">
            <div className="flex items-start gap-2">
              <BrainCircuit className="h-4 w-4 text-primary shrink-0 mt-0.5" />
              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between gap-2 text-[10px] text-muted-foreground">
                  <span className="font-semibold uppercase tracking-wide">
                    {result?.model_id || "model"} · {result?.vehicle_count ?? 0} detections
                  </span>
                  <span className="font-mono tabular-nums shrink-0">
                    {result ? `${formatSeconds(resultAgeS)} ago · ${formatMs(result.inference_latency_ms)}` : "waiting for first result"}
                  </span>
                </div>
                <p className="mt-0.5 line-clamp-2 text-xs text-foreground">
                  {result?.vlm_summary || result?.raw_response || (result ? "No summary in the last result." : "Waiting for the next inference result.")}
                </p>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
