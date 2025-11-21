# 智能眼镜控制中台

基于 FastAPI 的智能眼镜三路摄像头控制与监控服务，可在局域网内提供 Web 控制台，实现实时预览、开启/关闭摄像头、同步录制。

## 功能概览

- 三路 USB 摄像头（1 彩色 + 2 红外）实时 MJPEG 预览
- 摄像头启停控制、状态监视
- 多路同步录制，按照时间戳创建文件夹保存
- Web 控制台 UI，适配桌面与移动端
- REST API（`/api`）可供后续自动化接入

## 快速开始

```bash
cd /Users/andrew/mty/开发/smartphone-os/server
./scripts/run_dev.sh
```

首次运行会自动创建虚拟环境并安装依赖。启动后访问 `http://<开发板IP>:8000/`。

> 若开发板 Python 版本较旧，可手动创建虚拟环境并调整 `requirements.txt` 中依赖。

## 目录结构

- `backend/app/main.py`：FastAPI 入口，注册路由与 UI
- `backend/app/services/`：摄像头管理、录制模块等核心逻辑
- `backend/app/api/`：REST 接口
- `backend/app/templates/`：Jinja2 模板（Web 控制台界面）
- `backend/app/static/`：样式资源
- `backend/app/services/system_info.py`：设备电量/IP 信息探测
- `scripts/run_dev.sh`：开发启动脚本

## 部署建议

1. **系统依赖**：确保已安装 `python3`, `pip`, OpenCV 所需驱动（`opencv-python` 提供的大部分功能即可）。
2. **红外摄像头驱动（Pupil Cam2）**：
   - 安装底层库  
     - Debian/Ubuntu:
       ```bash
       sudo apt-get update
       sudo apt-get install libusb-1.0-0-dev libudev-dev cmake build-essential
       ```
     - macOS (Homebrew):
       ```bash
       brew install libusb libuvc cmake
       xcode-select --install    # 若尚未安装 Command Line Tools
       ```
   - 编译安装 `pyuvc`：
       ```bash
       pip install git+https://github.com/pupil-labs/pyuvc.git
       ```
     编译前请确认 `pkg-config` 能找到 `libusb` 与 `libuvc`。安装完成后，可运行
       ```bash
       python - <<'PY'
       import uvc
       for dev in uvc.device_list():
           print(dev)
       PY
       ```
     验证是否识别到 `Pupil Cam2 ID0/ID1`。若系统存在多路相同设备，可通过环境变量绑定：
       - `EYE0_LIBUVC_UID` / `EYE1_LIBUVC_UID`：指定红外摄像头的 `uid`（例如 `0:5`、`0:6`）
       - `EYE0_LIBUVC_ADDRESS` / `EYE1_LIBUVC_ADDRESS`：指定 `device_address`（十进制或 `0x` 十六进制）
       - `EYE0_ACCESS_METHOD` / `EYE1_ACCESS_METHOD`：强制使用 `libuvc` 或 `opencv`
       - `WORLD_ACCESS_METHOD`：若彩色摄像头也需要改为 `libuvc` 可设置该变量
     未配置时，系统将根据 Vendor/Product ID 自动匹配，但在同型号设备较多的情况下，建议显式指定 UID 或地址以避免冲突。
3. **服务守护**：可创建 systemd 单元 `/etc/systemd/system/smartglasses.service`：
   ```ini
   [Unit]
   Description=Smart Glasses Control Service
   After=network.target

   [Service]
   WorkingDirectory=/Users/andrew/mty/开发/smartphone-os/server/backend
   Environment="PATH=/Users/andrew/mty/开发/smartphone-os/server/backend/.venv/bin"
   ExecStart=/Users/andrew/mty/开发/smartphone-os/server/backend/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
   Restart=always

   [Install]
   WantedBy=multi-user.target
   ```
4. **网络访问**：确认开发板处于目标局域网，可先通过 `ifconfig` 或 `ip addr` 获取 IP，外部浏览器访问 `http://IP:8000/`。
5. **日志查看**：FastAPI/Uvicorn 默认输出至 stdout，可配合 `journalctl -u smartglasses.service -f` 查看。

## 硬件信息 & GPS 展示

Web 控制台会自动调用 `hardinfo` 与 `microcom` 获取硬件摘要和 GPS 状态（显示经纬度、海拔、速度、卫星数等）。如需启用该功能：

- 安装依赖：
  ```bash
  sudo apt-get install hardinfo microcom
  ```
- 若 GPS 模块通过串口连接，可配置以下环境变量（可在 systemd 或 shell 中设置）：

  | 变量 | 说明 | 默认值 |
  | ---- | ---- | ---- |
  | `GPS_SERIAL_DEVICE` | GPS 所在串口路径 | `/dev/ttyUSB0` |
  | `GPS_SERIAL_BAUD` | 串口波特率 | `9600` |
  | `GPS_READ_TIMEOUT` | 采集超时时间（秒） | `3.0` |
  | `GPS_SKIP_DEVICE_CHECK` | 设为 `1` 可跳过串口存在性检查 | `0` |
  | `GPS_SAMPLE_FILE` | 指向包含 NMEA 语句的文本文件，用于本地调试 | 空 |

- 可通过环境变量定制 `hardinfo` 行为：

  | 变量 | 说明 | 默认值 |
  | ---- | ---- | ---- |
  | `HARDINFO_SECTIONS` | 读取的模块，逗号分隔 | `devices.cpu,devices.memory,devices.storage,devices.network,devices.battery` |
  | `HARDINFO_SUMMARY_LIMIT` | 控制页面展示的键值条目数量 | `12` |
  | `HARDINFO_TIMEOUT` | 命令执行超时时间（秒） | `4.0` |

> 若上述命令或串口不可用，页面会优雅降级，仅展示基础系统信息。

## API 说明（节选）

- `GET /api/cameras/`：摄像头状态列表
- `POST /api/cameras/{camera_id}/start`：开启指定摄像头
- `POST /api/cameras/{camera_id}/stop`：关闭指定摄像头
- `GET /api/cameras/{camera_id}/stream`：MJPEG 码流（嵌入 `<img>` 即可播放）
- `POST /api/recording/start`：开始录制（默认全部摄像头）
- `POST /api/recording/stop`：停止录制
- `GET /api/recording/status`：录制状态
- `GET /api/algorithms/{algorithm_id}/stream/{camera_id}`：算法消费后的实时帧（MJPEG）

## 测试与验证

- 运行 `pytest`（后续提供单元测试样例）：
  ```bash
  cd /Users/andrew/mty/开发/smartphone-os/server/backend
  source .venv/bin/activate  # 若已创建虚拟环境
  pytest
  ```
- 手动验证步骤：
  1. 接入眼镜并确认系统识别到三个 `/dev/video*`
  2. 打开 Web 控制台，依次开启三个摄像头，确认画面方向与尺寸正确
  3. 点击“开始录制”，完成一次 10 秒录制并检查 `record/<timestamp>/` 中 MP4 文件是否生成

## 后续规划

- 引入 WebSocket / WebRTC，降低延迟并支持音频
- 增加摄像头参数调节（曝光/增益等）
- 集成设备诊断、日志上传等运维功能
- 针对非 UVC 红外摄像头，进一步完善基于 libuvc 的采集和调试工具

