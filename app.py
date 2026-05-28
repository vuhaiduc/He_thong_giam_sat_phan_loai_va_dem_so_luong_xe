from flask import Flask, render_template, jsonify, Response
from flask_cors import CORS
import threading
import json
import cv2 as cv
from ultralytics import YOLO
import numpy as np
import supervision as sv
import time
import torch
from blockchain_test import send_traffic_data, get_traffic_data, get_traffic_count, get_traffic_item
import queue

app = Flask(__name__)
CORS(app)

# Performance configuration for smoother web playback
# Use a lighter model by default for better real-time UX on web.
MODEL_PATH = "yolo11n.pt"
INFER_IMGSZ = 416
INFER_CONF = 0.3
SAVE_OUTPUT_VIDEO = False
JPEG_QUALITY = 50
STREAM_FPS = 10
ROI_TOP = 150
DEVICE = "cuda:0" if torch.cuda.is_available() else "cpu"
USE_HALF = DEVICE.startswith("cuda")

# Global variables for vehicle tracking
vehicle_stats = {
    "total": 0,
    "up": 0,
    "down": 0,
    "by_type": {
        "car": {"total": 0, "up": 0, "down": 0},
        'truck': {'total': 0, 'up': 0, 'down': 0},
    },
    'last_updated': 0,
    'fps': 0,
    'frames_processed': 0,
    'blockchain': {
        'blocks_sent': 0,
        'last_tx_hash': '',
        'last_payload_hash': '',
        'last_block_at': 0,
        'last_block_data': '',
        'last_error': ''
    }
}

current_frame = None
current_jpeg = None
frame_lock = threading.Lock()
processing_active = True
# Blockchain config
BLOCK_INTERVAL = 20
next_block_time = 0
blocks_history = []  # Lưu lịch sử block (tối đa 100 block)
blocks_history_lock = threading.Lock()
blockchain_queue = queue.Queue()
# Initialize YOLO model
model = YOLO(MODEL_PATH)
video_path = "DATA/INPUTS/cars_on_highway.mp4"

# Video properties
try:
    video_info = sv.VideoInfo.from_video_path(video_path)
    w, h, fps = video_info.width, video_info.height, video_info.fps
except Exception as e:
    print(f"Error loading video: {e}")
    w, h, fps = 1280, 720, 60

# Setup annotators
thickness = sv.calculate_optimal_line_thickness(resolution_wh=(w, h))
text_scale = sv.calculate_optimal_text_scale(resolution_wh=(w, h))

box_annotator = sv.RoundBoxAnnotator(thickness=thickness, color_lookup=sv.ColorLookup.TRACK)
label_annotator = sv.LabelAnnotator(text_scale=text_scale, text_thickness=thickness,
                                    text_position=sv.Position.TOP_CENTER, color_lookup=sv.ColorLookup.TRACK)
trace_annotator = sv.TraceAnnotator(thickness=thickness, trace_length=fps * 2,
                                    position=sv.Position.CENTER, color_lookup=sv.ColorLookup.TRACK)

# Tracker setup
tracker = sv.ByteTrack(frame_rate=fps)
smoother = sv.DetectionsSmoother()
class_names = model.names
vehicle_classes = ['car', 'truck']
selected_classes = [cls_id for cls_id, class_name in model.names.items() if
                    class_name in vehicle_classes]

# Counting configuration
limits = [0, 300, 1280, 300]
partition_limit = 550
vehicle_info = {}

# Realtime cumulative stats vs interval stats
# - `vehicle_stats` holds cumulative realtime totals since app start (shown on dashboard)
# - `interval_stats` holds counts for the current blockchain interval (e.g. 20s)
#   These are the values we send to the blockchain and reset after a successful push.
interval_stats = {
    'interval_total': 0,
    'interval_up': 0,
    'interval_down': 0,
    'interval_car': 0,
    'interval_truck': 0,
    'interval_bus': 0,
    'interval_motorbike': 0,
}
interval_lock = threading.Lock()


def draw_overlay(frame, pt1, pt2, alpha=0.25, color=(51, 68, 255), filled=True):
    """Draws a semi-transparent overlay rectangle."""
    overlay = frame.copy()
    rect_color = color if filled else (0, 0, 0)
    cv.rectangle(overlay, pt1, pt2, rect_color, cv.FILLED if filled else 1)
    cv.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)


def count_vehicle_total(track_id, cx, cy):
    """Counts vehicles crossing the line once."""
    if (limits[0] < cx < limits[2] and limits[1] - 10 < cy < limits[1] + 10 and 
        track_id not in vehicle_info):
        return True
    return False


def get_vehicle_direction(track_id, cx, cy):
    """Determines if vehicle is going up or down."""
    if limits[0] < cx < partition_limit and limits[1] - 10 < cy < limits[1] + 10:
        return 'up'
    elif partition_limit < cx < limits[2] and limits[1] - 15 < cy < limits[1] + 15:
        return 'down'
    return None


def process_frame(frame, detections):
    """Process frame and update statistics."""
    detections = detections[np.isin(detections.class_id, selected_classes)]
    labels = [f"#{track_id} {class_names[cls_id]}" for track_id, cls_id in
              zip(detections.tracker_id, detections.class_id)]

    label_annotator.annotate(frame, detections=detections, labels=labels)
    box_annotator.annotate(frame, detections=detections)
    trace_annotator.annotate(frame, detections=detections)

    for track_id, center_point, cls_id in zip(detections.tracker_id,
                                              detections.get_anchors_coordinates(anchor=sv.Position.CENTER),
                                              detections.class_id):
        cx, cy = map(int, center_point)
        cv.circle(frame, (cx, cy), 4, (0, 255, 255), cv.FILLED)

        class_name = class_names[cls_id]

        # Count total vehicles
        if count_vehicle_total(track_id, cx, cy):
            vehicle_info[track_id] = {
                'class': class_name,
                'counted_total': True,
                'counted_direction': False,
                'direction': None
            }
            vehicle_stats['total'] += 1
            if class_name in vehicle_stats['by_type']:
                vehicle_stats['by_type'][class_name]['total'] += 1
            # Also increment interval counters (these are sent to blockchain each interval)
            with interval_lock:
                interval_stats['interval_total'] += 1
                if class_name == 'car':
                    interval_stats['interval_car'] += 1
                elif class_name == 'truck':
                    interval_stats['interval_truck'] += 1
                elif class_name == 'bus':
                    interval_stats['interval_bus'] += 1
                elif class_name == 'motorbike':
                    interval_stats['interval_motorbike'] += 1

        # Count by direction
        if track_id in vehicle_info and not vehicle_info[track_id]['counted_direction']:
            direction = get_vehicle_direction(track_id, cx, cy)
            if direction:
                vehicle_info[track_id]['counted_direction'] = True
                vehicle_info[track_id]['direction'] = direction
                
                if direction == 'up':
                    vehicle_stats['up'] += 1
                    if class_name in vehicle_stats['by_type']:
                        vehicle_stats['by_type'][class_name]['up'] += 1
                    # interval direction counter
                    with interval_lock:
                        interval_stats['interval_up'] += 1
                else:
                    vehicle_stats['down'] += 1
                    if class_name in vehicle_stats['by_type']:
                        vehicle_stats['by_type'][class_name]['down'] += 1
                    # interval direction counter
                    with interval_lock:
                        interval_stats['interval_down'] += 1
def push_to_blockchain():
    """Enqueue a snapshot of current stats to be sent to blockchain by worker thread."""
    try:
        realtime_iso = time.strftime('%H:%M:%S', time.localtime())
        # Send only interval stats (counts within the last BLOCK_INTERVAL)
        # Read interval stats under lock and skip enqueue if interval is empty
        with interval_lock:
            current_total = interval_stats.get('interval_total', 0)
            if current_total == 0:
                # No vehicles in this interval; do not create an empty block
                return

            payload = {
                'lane': 1,
                'car': interval_stats.get('interval_car', 0),
                'truck': interval_stats.get('interval_truck', 0),
                'bus': interval_stats.get('interval_bus', 0),
                'motorbike': interval_stats.get('interval_motorbike', 0),
                'total': current_total,
                'up': interval_stats.get('interval_up', 0),
                'down': interval_stats.get('interval_down', 0),
                'timestamp': realtime_iso,
            }
        # Non-blocking enqueue; worker thread (daemon) will process it
        blockchain_queue.put(payload)
    except Exception as e:
        vehicle_stats['blockchain']['last_error'] = str(e)
        print("Failed to enqueue blockchain payload:", e)


def _blockchain_worker():
    """Worker thread that sends queued blockchain payloads without blocking video loop."""
    while True:
        payload = blockchain_queue.get()
        try:
            blockchain_result = send_traffic_data(
                lane=payload.get('lane', 1),
                car=payload.get('car', 0),
                truck=payload.get('truck', 0),
                total=payload.get('total', 0),
                up=payload.get('up', 0),
                down=payload.get('down', 0),
                timestamp=payload.get('timestamp', '')
            )
            if blockchain_result is None:
                vehicle_stats['blockchain']['last_error'] = 'Khong gui duoc giao dich len blockchain'
                continue

            chain_index = blockchain_result.get('chain_index')
            if chain_index is None:
                try:
                    chain_index = len(get_traffic_data()) - 1
                    if chain_index < 0:
                        chain_index = None
                except Exception:
                    chain_index = None

            vehicle_stats['blockchain']['blocks_sent'] += 1
            vehicle_stats['blockchain']['last_tx_hash'] = blockchain_result.get('tx_hash', '')
            vehicle_stats['blockchain']['last_payload_hash'] = blockchain_result.get('payload_hash', '')
            vehicle_stats['blockchain']['last_block_at'] = int(time.time())
            vehicle_stats['blockchain']['last_block_data'] = json.dumps(blockchain_result.get('payload', {}), ensure_ascii=True)
            vehicle_stats['blockchain']['last_error'] = ''

            # Build block info and store to history with lock
            block_info = {
                'block_number': vehicle_stats['blockchain']['blocks_sent'],
                'up': payload.get('up', 0),
                'down': payload.get('down', 0),
                'car': payload.get('car', 0),
                'truck': payload.get('truck', 0),
                'total': payload.get('total', 0),
                'timestamp': payload.get('timestamp', ''),
                'payload_hash': vehicle_stats['blockchain']['last_payload_hash'],
                'payload': blockchain_result.get('payload', {}),
                'tx_hash': vehicle_stats['blockchain']['last_tx_hash'],
                'chain_index': chain_index,
            }

            with blocks_history_lock:
                blocks_history.append(block_info)
                if len(blocks_history) > 100:
                    blocks_history.pop(0)

            # Reset interval counters after a successful blockchain push
            with interval_lock:
                for k in list(interval_stats.keys()):
                    interval_stats[k] = 0

            # Print concise console line for each block
            print(f"\n📦 Block {block_info['block_number']}:")
            print(f"   {{'up': {block_info['up']}, 'down': {block_info['down']}, 'car': {block_info['car']}, 'truck': {block_info['truck']}, 'total': {block_info['total']}, 'timestamp': '{block_info['timestamp']}', 'tx': '{block_info['tx_hash'][:8]}...'}}\n")
        except Exception as e:
            vehicle_stats['blockchain']['last_error'] = str(e)
            print("Blockchain worker error:", e)
        finally:
            blockchain_queue.task_done()

def draw_statistics_on_frame(frame):
    """Draw statistics text on the frame."""
    y_offset = 30
    stats_text = [
        f"TOTAL: {vehicle_stats['total']}",
        f"UP: {vehicle_stats['up']} | DOWN: {vehicle_stats['down']}",
        f"Car: {vehicle_stats['by_type']['car']['total']} (U:{vehicle_stats['by_type']['car']['up']} D:{vehicle_stats['by_type']['car']['down']})",
        f"Truck: {vehicle_stats['by_type']['truck']['total']} (U:{vehicle_stats['by_type']['truck']['up']} D:{vehicle_stats['by_type']['truck']['down']})",
    ]
    
    for i, text in enumerate(stats_text):
        cv.putText(frame, text, (10, y_offset + i * 25), cv.FONT_HERSHEY_SIMPLEX, 
                  0.6, (0, 255, 0), 2)


def video_processing_thread():
    """Background thread to process video frames."""
    global current_frame, current_jpeg, processing_active, next_block_time
    
    cap = cv.VideoCapture(video_path)
    cap.set(cv.CAP_PROP_BUFFERSIZE, 1)
    output_path = "DATA/OUTPUTS/car_counter_web.mp4"
    out = None
    if SAVE_OUTPUT_VIDEO:
        out = cv.VideoWriter(output_path, cv.VideoWriter_fourcc(*"mp4v"), fps, (w, h))

    if not cap.isOpened():
        print("Error: couldn't open the video!")
        return

    frame_count = 0
    start_time = time.time()
    next_block_time = start_time + BLOCK_INTERVAL

    # Precompute ROI mask once instead of allocating it every frame.
    mask_b = np.zeros((h, w, 3), dtype=np.uint8)
    mask_b[ROI_TOP:, :] = 255

    while cap.isOpened() and processing_active:
        ret, frame = cap.read()
        if not ret:
            # Restart video
            cap.set(cv.CAP_PROP_POS_FRAMES, 0)
            continue

        ROI = cv.bitwise_and(frame, mask_b)
        
        # YOLO detection
        results = model(
            ROI,
            verbose=False,
            imgsz=INFER_IMGSZ,
            conf=INFER_CONF,
            classes=selected_classes,
            device=DEVICE,
            half=USE_HALF,
        )[0]
        detections = sv.Detections.from_ultralytics(results)
        detections = tracker.update_with_detections(detections)
        detections = smoother.update_with_detections(detections)

        if detections.tracker_id is not None:
            sv.draw_line(frame, start=sv.Point(x=limits[0], y=limits[1]), 
                        end=sv.Point(x=limits[2], y=limits[3]),
                        color=sv.Color.RED, thickness=4)
            draw_overlay(frame, (0, 200), (1287, 400), alpha=0.2)
            process_frame(frame, detections)

        draw_statistics_on_frame(frame)
        
        if out is not None:
            out.write(frame)

        # Encode once in producer thread, reuse bytes in web stream.
        ok, buffer = cv.imencode('.jpg', frame, [int(cv.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
        if ok:
            jpeg_bytes = buffer.tobytes()
        else:
            jpeg_bytes = None

        with frame_lock:
            current_frame = frame
            if jpeg_bytes is not None:
                current_jpeg = jpeg_bytes

        frame_count += 1
        vehicle_stats['frames_processed'] = frame_count
        vehicle_stats['last_updated'] = int(time.time())
        now = time.time()
        if now >= next_block_time:
            push_to_blockchain()
            next_block_time = now + BLOCK_INTERVAL
        # Calculate FPS
        elapsed = time.time() - start_time
        if elapsed > 0:
            vehicle_stats['fps'] = frame_count / elapsed

    cap.release()
    if out is not None:
        out.release()


# Web Routes
@app.route('/')
def index():
    """Serve the main dashboard."""
    return render_template('dashboard.html')


@app.route('/api/stats')
def get_stats():
    """API endpoint to get current statistics."""
    response = dict(vehicle_stats)
    response['is_running'] = processing_active
    return jsonify(response)


@app.route('/api/reset', methods=['POST'])
def reset_stats():
    """API endpoint to reset statistics."""
    global vehicle_info, next_block_time
    vehicle_stats['total'] = 0
    vehicle_stats['up'] = 0
    vehicle_stats['down'] = 0
    for vehicle_type in vehicle_stats['by_type']:
        vehicle_stats['by_type'][vehicle_type] = {'total': 0, 'up': 0, 'down': 0}
    vehicle_stats['frames_processed'] = 0
    vehicle_stats['fps'] = 0
    vehicle_stats['last_updated'] = int(time.time())
    global blocks_history
    vehicle_stats['blockchain'] = {
        'blocks_sent': 0,
        'last_tx_hash': '',
        'last_payload_hash': '',
        'last_block_at': 0,
        'last_block_data': '',
        'last_error': ''
    }
    next_block_time = time.time() + BLOCK_INTERVAL
    blocks_history = []  # Xóa lịch sử block khi reset
    vehicle_info = {}
    return jsonify({'status': 'reset successful'})


@app.route('/api/blocks')
def get_blocks():
    """API endpoint to get block history."""
    return jsonify({
        'total_blocks': len(blocks_history),
        'blocks': blocks_history
    })

@app.route('/api/blocks/verify/<int:block_number>')
def verify_block(block_number):
    """Verify a stored block against the on-chain contract data."""
    if block_number < 1 or block_number > len(blocks_history):
        return jsonify({
            'ok': False,
            'message': 'Block khong ton tai trong lich su'
        }), 404

    stored_block = blocks_history[block_number - 1]
    local_payload = stored_block.get('payload', {})

    # Try fast path: if block_info contains a valid chain_index, fetch only that item
    chain_index = stored_block.get('chain_index')
    chain_block = None

    if isinstance(chain_index, int):
        count = get_traffic_count()
        if count is None:
            return jsonify({
                'ok': False,
                'message': 'Khong doc duoc du lieu tu blockchain. Hay kiem tra RPC va CONTRACT_ADDRESS',
                'stored': stored_block,
                'chain_count': 0,
                'expected': local_payload,
            }), 409

        if 0 <= chain_index < count:
            chain_block = get_traffic_item(chain_index)

    def normalize_payload(payload):
        return {
            'lane': int(payload.get('lane', -1)),
            'car': int(payload.get('car', -1)),
            'truck': int(payload.get('truck', -1)),
            'total': int(payload.get('total', -1)),
            'up': int(payload.get('up', -1)),
            'down': int(payload.get('down', -1)),
            'timestamp': str(payload.get('timestamp', '')),
        }

    expected_payload = normalize_payload(local_payload)

    # If fast-path lookup failed, fall back to scanning the chain (single full read)
    if chain_block is None:
        chain_blocks = get_traffic_data()
        if not chain_blocks:
            return jsonify({
                'ok': False,
                'message': 'Khong doc duoc du lieu tu blockchain. Hay kiem tra RPC va CONTRACT_ADDRESS',
                'stored': stored_block,
                'chain_count': 0,
                'expected': local_payload,
            }), 409

        for index, candidate in enumerate(chain_blocks):
            if normalize_payload(candidate) == expected_payload:
                chain_block = candidate
                chain_index = index
                break

    if chain_block is None:
        return jsonify({
            'ok': False,
            'message': 'Khong tim thay du lieu trung khop tren blockchain',
            'stored': stored_block,
            'chain_count': len(chain_blocks),
            'expected': expected_payload,
        }), 409

    chain_payload = normalize_payload(chain_block)
    matches = {field: expected_payload[field] == chain_payload[field] for field in expected_payload}
    payload_matches = all(matches.values())

    result = {
        'ok': payload_matches,
        'block_number': block_number,
        'stored': stored_block,
        'chain': chain_block,
        'chain_index': chain_index,
        'matches': matches,
    }

    result['message'] = 'Xac thuc thanh cong' if payload_matches else 'Du lieu khong khop'
    print(f"\n=== VERIFY Block {block_number} - {'SUCCESS' if payload_matches else 'MISMATCH'} ===")
    print(f"Expected: {expected_payload}")
    print(f"Chain:    {chain_payload}")
    for field in expected_payload:
        exp_val = expected_payload[field]
        chain_val = chain_payload[field]
        match_status = "✓" if matches[field] else "✗"
        print(f"  {match_status} {field}: {exp_val!r} ({type(exp_val).__name__}) vs {chain_val!r} ({type(chain_val).__name__})")
    print()
    return jsonify(result)


@app.route('/api/stop', methods=['POST'])
def stop_processing():
    """API endpoint to stop counting and video processing."""
    global processing_active
    processing_active = False
    return jsonify({'status': 'stopped'})


@app.route('/video_feed')
def video_feed():
    """Stream video with statistics."""
    def generate():
        placeholder = np.zeros((h, w, 3), dtype=np.uint8)
        ok, placeholder_buf = cv.imencode('.jpg', placeholder, [int(cv.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
        placeholder_bytes = placeholder_buf.tobytes() if ok else b''

        while True:
            with frame_lock:
                frame_data = current_jpeg if current_jpeg is not None else placeholder_bytes
            
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n'
                   b'Content-Length: ' + str(len(frame_data)).encode() + b'\r\n\r\n' +
                   frame_data + b'\r\n')
            
            time.sleep(1.0 / STREAM_FPS)

    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')


if __name__ == '__main__':
    # Start blockchain worker thread (daemon)
    blockchain_worker_thread = threading.Thread(target=_blockchain_worker, daemon=True)
    blockchain_worker_thread.start()

    # Start video processing thread
    video_thread = threading.Thread(target=video_processing_thread, daemon=True)
    video_thread.start()
    
    # Start Flask server
    print("Starting web server at http://localhost:5000")
    app.run(debug=False, threaded=True, host='0.0.0.0', port=5000)
