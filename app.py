from flask import Flask, request, render_template, redirect, url_for, jsonify
from ultralytics import YOLO
import cv2
import os
import subprocess
import shutil

app = Flask(__name__)
model = YOLO("yolov10n/weights.pt")

UPLOAD_FOLDER = 'uploads'
PROCESSED_FOLDER = 'static'
FRAMES_FOLDER = 'frames'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['PROCESSED_FOLDER'] = PROCESSED_FOLDER
app.config['FRAMES_FOLDER'] = FRAMES_FOLDER

ffmpeg_progress = 0
yolo_progress = 0
detection_data = []

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    global ffmpeg_progress, yolo_progress, detection_data
    ffmpeg_progress = 0
    yolo_progress = 0
    detection_data = []
    if 'file' not in request.files:
        return redirect(request.url)
    file = request.files['file']
    if file.filename == '':
        return redirect(request.url)
    if file:
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
        file.save(file_path)
        process_video(file_path)
        return redirect(url_for('processed_file', filename=file.filename))
    return redirect(request.url)

def extract_frames(input_video, output_folder, frame_pattern):
    global ffmpeg_progress
    os.makedirs(output_folder, exist_ok=True)
    extract_frames_command = [
        'ffmpeg', '-i', input_video, '-vf', 'select=not(mod(n\\,1))', '-vsync', 'vfr', f'{output_folder}/{frame_pattern}'
    ]
    subprocess.run(extract_frames_command, check=True)
    ffmpeg_progress = 100

def combine_frames(input_pattern, output_video, framerate=30):
    combine_frames_command = [
        'ffmpeg', '-framerate', str(framerate), '-i', input_pattern, '-c:v', 'libx264', '-r', str(framerate), '-pix_fmt', 'yuv420p', output_video
    ]
    subprocess.run(combine_frames_command, check=True)

def delete_frames(folder):
    shutil.rmtree(folder)

def process_video(file_path):
    global yolo_progress, detection_data
    frames_folder = app.config['FRAMES_FOLDER']
    frame_pattern = 'frame%03d.png'
    output_path = os.path.join(app.config['PROCESSED_FOLDER'], 'processed_' + os.path.basename(file_path))

    # Extract frames from the video
    extract_frames(file_path, frames_folder, frame_pattern)

    # Process each frame using YOLO
    frames = sorted(os.listdir(frames_folder))
    total_frames = len(frames)
    
    detected_objects = {}
    previous_detections = []

    for i, frame in enumerate(frames):
        frame_path = os.path.join(frames_folder, frame)
        img = cv2.imread(frame_path)
        results = model.predict(source=img)
        new_detections = []

        for result in results:
            boxes = result.boxes
            for box in boxes:
                x1, y1, x2, y2 = box.xyxy[0]
                label = result.names[int(box.cls)]
                confidence = box.conf.item()  

                cv2.rectangle(img, (int(x1), int(y1)), (int(x2), int(y2)), (255, 0, 0), 2)
                cv2.putText(img, f'{label} {confidence:.2f}', (int(x1), int(y1)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 2)

                current_bbox = (x1, y1, x2, y2)
                if not any(iou(current_bbox, prev_bbox) > 0.5 for prev_bbox in previous_detections):
                    if label not in detected_objects:
                        detected_objects[label] = 0
                    detected_objects[label] += 1
                    new_detections.append(current_bbox)

                    detection_data.append({
                        'label': label,
                        'confidence': confidence,
                        'coordinates': (int(x1), int(y1), int(x2), int(y2))
                    })

        previous_detections = new_detections
        cv2.imwrite(frame_path, img)
        yolo_progress = int((i / total_frames) * 100)
        print(f'Processing frame {i+1}/{total_frames} ({yolo_progress}%)')

    combine_frames(f'{frames_folder}/{frame_pattern}', output_path)

    delete_frames(frames_folder)

    print(f"Detected objects: {detected_objects}")

def iou(bbox1, bbox2):
    x1_min, y1_min, x1_max, y1_max = bbox1
    x2_min, y2_min, x2_max, y2_max = bbox2

    inter_x_min = max(x1_min, x2_min)
    inter_y_min = max(y1_min, y2_min)
    inter_x_max = min(x1_max, x2_max)
    inter_y_max = min(y1_max, y2_max)

    inter_area = max(0, inter_x_max - inter_x_min) * max(0, inter_y_max - inter_y_min)

    bbox1_area = (x1_max - x1_min) * (y1_max - y1_min)
    bbox2_area = (x2_max - x2_min) * (y2_max - y2_min)

    iou = inter_area / float(bbox1_area + bbox2_area - inter_area)

    return iou

@app.route('/ffmpeg_progress')
def get_ffmpeg_progress():
    global ffmpeg_progress
    return jsonify(progress=ffmpeg_progress)

@app.route('/yolo_progress')
def get_yolo_progress():
    global yolo_progress
    return jsonify(progress=yolo_progress)

@app.route('/processed/<filename>')
def processed_file(filename):
    return render_template('processed.html', filename='processed_' + filename, detection_data=detection_data)

@app.route('/contribute', methods=['GET', 'POST'])
def contribute():
    if request.method == 'POST':
        name = request.form.get('name', 'you')

        video_file = request.files.get('video')
        image_files = request.files.getlist('images')
        label_file = request.files.get('labels')

        if not video_file and not image_files and not label_file:
            return render_template('contribute.html', error='Please upload at least one file.')

        if video_file and video_file.filename != '':
            video_path = os.path.join(app.config['UPLOAD_FOLDER'], 'contributed_videos', video_file.filename)
            os.makedirs(os.path.dirname(video_path), exist_ok=True)
            video_file.save(video_path)

        if image_files and label_file and label_file.filename != '':
            for image_file in image_files:
                if image_file.filename != '':
                    image_path = os.path.join(app.config['UPLOAD_FOLDER'], 'contributed_images', image_file.filename)
                    os.makedirs(os.path.dirname(image_path), exist_ok=True)
                    image_file.save(image_path)

            label_path = os.path.join(app.config['UPLOAD_FOLDER'], 'contributed_labels', label_file.filename)
            os.makedirs(os.path.dirname(label_path), exist_ok=True)
            label_file.save(label_path)

        with open('contributors.txt', 'a') as file:
            file.write(f'{name}\n')

        return render_template('contribute_success.html', name=name)
    
    return render_template('contribute.html')

if __name__ == "__main__":
    app.run(debug=True)
