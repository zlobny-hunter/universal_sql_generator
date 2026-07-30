import socket
import uvicorn


def get_local_ip():
    """Автоматическое определение локального IP-адреса хоста"""
    try:
        # Создаем временное UDP-соединение (не отправляет реальных пакетов)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


if __name__ == "__main__":
    host_ip = get_local_ip()
    port = 8000

    print(f"Server is running on:")
    print(f" -> Local:   http://127.0.0.1:{port}")
    print(f" -> Network: http://{host_ip}:{port}")

    # 0.0.0.0 позволяет принимать подключения как с этого же ПК, так и по локальной сети/VPN
    uvicorn.run("web.app:app", host="0.0.0.0", port=port, reload=True)
