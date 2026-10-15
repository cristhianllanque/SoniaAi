"""One camera producer shared by detection and authenticated monitor clients."""
import logging
import threading
import time

from . import config

logger = logging.getLogger(__name__)


class YoloEngine:
    def __init__(self, camera_index=None):
        self.camera_index = config.CAMERA_INDEX if camera_index is None else camera_index
        self.condition = threading.Condition()
        self.stop_event = threading.Event()
        self.thread = None
        self.frame = None
        self.sequence = 0
        self.state = 'stopped'
        self.error = None
        self.person_present_since = None
        self.is_interested = False
        self.lock_until = 0.0
        self._yolo_model = None

    def start(self):
        with self.condition:
            if self.thread and self.thread.is_alive():
                return
            self.stop_event.clear()
            self.state = 'starting'
            self.error = None
            self.frame = None
            self.person_present_since = None
            self.is_interested = False
            self.lock_until = 0
            self.thread = threading.Thread(target=self._capture, name='camera-detection', daemon=True)
            self.thread.start()

    def stop(self):
        self.stop_event.set()
        with self.condition:
            self.frame = None
            self.is_interested = False
            self.person_present_since = None
            self.lock_until = 0
            self.condition.notify_all()
        if self.thread:
            self.thread.join(timeout=5)
        with self.condition:
            self.state = 'stopping' if self.thread and self.thread.is_alive() else 'stopped'

    def status(self):
        with self.condition:
            return {'state': self.state, 'error': self.error}

    def _capture(self):
        cap = hands = None
        try:
            import cv2
            from ultralytics import YOLO
            from mediapipe.python.solutions import hands as mp_hands
            model_path = config.BASE_DIR / 'yolov8n.pt'
            if not model_path.is_file():
                raise RuntimeError('Falta el modelo de detección.')
            cap = cv2.VideoCapture(self.camera_index)
            if not cap.isOpened() and self.camera_index != 0:
                cap.release()
                cap = cv2.VideoCapture(0)
            if not cap.isOpened():
                raise RuntimeError('No se encontró una cámara disponible.')
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            if self._yolo_model is None:
                self._yolo_model = YOLO(str(model_path))
            model = self._yolo_model
            hands = mp_hands.Hands(max_num_hands=2, min_detection_confidence=0.7, min_tracking_confidence=0.5)
            with self.condition:
                self.state = 'running'
            failures = 0
            while not self.stop_event.is_set():
                started = time.monotonic()
                success, frame = cap.read()
                if not success:
                    failures += 1
                    if failures >= 10:
                        raise RuntimeError('Se perdió la conexión con la cámara.')
                    self.stop_event.wait(0.2)
                    continue
                failures = 0
                results = model.predict(frame, classes=[0], verbose=False)
                detected = any(len(result.boxes) for result in results)
                hand_results = hands.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)) if detected else None
                raised = bool(hand_results and hand_results.multi_hand_landmarks and any(
                    hand.landmark[8].y < hand.landmark[0].y - 0.2
                    for hand in hand_results.multi_hand_landmarks
                ))
                now = time.monotonic()
                with self.condition:
                    if not detected:
                        self.person_present_since = None
                    elif self.person_present_since is None:
                        self.person_present_since = now
                    ready = detected and (raised or now - self.person_present_since >= 7)
                    if ready and now >= self.lock_until:
                        self.is_interested = True
                        self.lock_until = now + 90  # Recovery even if the browser closes.
                for result in results:
                    for box in result.boxes:
                        x1, y1, x2, y2 = map(int, box.xyxy[0])
                        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 180, 0), 2)
                ok, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
                if ok:
                    with self.condition:
                        self.frame = buffer.tobytes()
                        self.sequence += 1
                        self.condition.notify_all()
                self.stop_event.wait(max(0, 1 / config.CAMERA_FPS - (time.monotonic() - started)))
        except Exception:
            logger.exception('Falló la detección de cámara.')
            with self.condition:
                self.state = 'error'
                self.error = 'No se pudo iniciar o mantener la cámara. Revisa la conexión e intenta otra vez.'
        finally:
            if hands:
                hands.close()
            if cap:
                cap.release()
            with self.condition:
                self.frame = None
                self.is_interested = False
                if self.stop_event.is_set():
                    self.state = 'stopped'
                self.condition.notify_all()

    def generate_frames(self):
        seen = -1
        while not self.stop_event.is_set():
            with self.condition:
                self.condition.wait_for(
                    lambda: (self.frame is not None and self.sequence != seen) or self.state in ('error', 'stopped') or self.stop_event.is_set(),
                    timeout=2,
                )
                if self.state in ('error', 'stopped') or self.stop_event.is_set():
                    return
                if self.frame is None or self.sequence == seen:
                    continue
                frame, seen = self.frame, self.sequence
            yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + frame + b'\r\n'

    def check_interest(self):
        with self.condition:
            interested = self.is_interested
            self.is_interested = False
            return interested

    def reset_lock(self):
        with self.condition:
            self.lock_until = time.monotonic() + 10
            self.person_present_since = None
            self.is_interested = False


engine = YoloEngine()


def get_engine():
    return engine
