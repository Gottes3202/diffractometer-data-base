import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, List
from datetime import date
import psycopg2 as ps2
from psycopg2.extras import RealDictCursor
import uvicorn
from dotenv import load_dotenv

app = FastAPI(title="Дифрактометры")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL")

class Devices(BaseModel):
    serial_number: str
    order_number: Optional[str] = None
    uop: Optional[str] = None
    sgp_date: Optional[date] = None
    status: Optional[str] = None

class DeviceInfo(BaseModel):
    customer: Optional[str] = None
    receiver: Optional[str] = None
    accessories: Optional[str] = None
    extra_equipment: Optional[str] = None
    extra_requirements: Optional[str] = None
    comments: Optional[str] = None
    orders: Optional[str] = None
   
class DeviceFull(Devices, DeviceInfo):
    id: Optional[int] = None
    last_update: Optional[date] = None

def get_db_connection():
    return ps2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

@app.get("/devices", response_model=List[DeviceFull])
def get_all_devices():
    try:
        connection = get_db_connection()
        cursor = connection.cursor()

        cursor.execute("""
            SELECT i.*, d.*
            FROM devices i
            LEFT JOIN devices_info d ON i.id = d.device_id
            ORDER BY i.id
        """)

        devices = cursor.fetchall()
        
        cursor.close()
        connection.close()

        return devices
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/device/{serial_number}", response_model=DeviceFull)
def get_device(serial_number: str):
    try:
        connection = get_db_connection()
        cursor = connection.cursor()

        cursor.execute("""
            SELECT i.*, d.*
            FROM devices i
            LEFT JOIN devices_info d ON i.id = d.device_id
            WHERE i.serial_number = %s
        """, (serial_number,))
        
        device = cursor.fetchone()
        
        cursor.close()
        connection.close()

        if not device:
            raise HTTPException(status_code=404, detail="Прибор не найден")
        
        return device
    
    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@app.put("/device/{serial_number}")
def update_device(serial_number: str, device: DeviceFull):
    try:
        connection = get_db_connection()
        cursor = connection.cursor()

        cursor.execute("SELECT id FROM devices WHERE serial_number = %s", (serial_number,))
        existing = cursor.fetchone()

        if existing:
            device_id = existing["id"]
            cursor.execute("""
                UPDATE devices
                SET order_number = %s,
                    uop = %s,
                    sgp_date = %s,
                    status = %s
                WHERE id = %s
                RETURNING id
            """, (
                device.order_number,
                device.uop,
                device.sgp_date,
                device.status,
                device_id
            ))

        else:
            cursor.execute("""
                INSERT INTO devices (serial_number, order_number, uop, sgp_date, status)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
            """, (
                serial_number,
                device.order_number, 
                device.uop, 
                device.sgp_date,
                device.status
            ))

            result = cursor.fetchone()
            device_id = result["id"] if result else None

        if not device_id:
            connection.rollback()
            cursor.close()
            connection.close()
            raise HTTPException(status_code=500, detail="Не удалось получить ID прибора")
        
        cursor.execute("SELECT id FROM devices_info WHERE device_id = %s", (device_id,))
        info_exists = cursor.fetchone()

        if info_exists:
            cursor.execute("""
                UPDATE devices_info
                SET customer = %s,
                    receiver = %s,
                    accessories = %s,
                    extra_equipment = %s,
                    extra_requirements = %s,
                    comments = %s,
                    orders = %s,
                    last_update = CURRENT_DATE
                WHERE device_id = %s       
            """, (
                device.customer,
                device.receiver,
                device.accessories,
                device.extra_equipment,
                device.extra_requirements,
                device.comments,
                device.orders,
                device_id
            ))
        
        else:
            cursor.execute("""
                INSERT INTO devices_info (
                    device_id, customer, receiver, accessories,
                    extra_equipment, extra_requirements, comments, orders, last_update    
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_DATE)
            """, (
                device_id, 
                device.customer,
                device.receiver,
                device.accessories,
                device.extra_equipment,
                device.extra_requirements,
                device.comments,
                device.orders
            ))

        connection.commit()

        cursor.close()
        connection.close()

        return {"message": "Данные обновлены", "serial_number": serial_number}
    
    except HTTPException:
        raise

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    

@app.delete("/device/{serial_number}")
def delete_device(serial_number: str):
    try:
        connection = get_db_connection()
        cursor = connection.cursor()

        cursor.execute("DELETE FROM devices WHERE serial_number = %s", (serial_number,))

        connection.commit()

        cursor.close()
        connection.close()

        return {"message": f"Прибор {serial_number} удален"}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    

@app.post("/device")
def create_device(serial_number: str):
    try:
        connection = get_db_connection()
        cursor = connection.cursor()

        cursor.execute("SELECT id FROM devices WHERE serial_number = %s", (serial_number,))
        existing = cursor.fetchone()

        if existing:
            cursor.close()
            connection.close()
            raise HTTPException(status_code=400, detail="Прибор с таким серийным номером уже существует")
        
        cursor.execute("""
            INSERT INTO devices (serial_number)
            VALUES (%s)
            RETURNING id
        """, (serial_number,))

        result = cursor.fetchone()
        device_id = result["id"] if result else None

        if not device_id:
            connection.rollback()
            cursor.close()
            connection.close()
            raise HTTPException(status_code=500, detail="Не удалось создать прибор")
        
        cursor.execute("""
            INSERT INTO devices_info (
                device_id,
                customer,
                receiver,
                accessories,
                extra_equipment,
                extra_requirements,
                comments,
                orders,
                last_update           
            )
            VALUES (%s, NULL, NULL, NULL, NULL, NULL, NULL, NULL, CURRENT_DATE)
        """, (device_id,))

        connection.commit()
        cursor.close()
        connection.close()

        return {"message": "Прибор создан", "Серийный номер:": serial_number}
    
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


if not os.path.exists("static"):
    os.makedirs("static")

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", response_class=HTMLResponse)
async def serve_frontedn():
    with open("static/index.html", "r", encoding="utf-8") as f:
        return f.read()

if __name__ == "__main__":
    uvicorn.run(app, host="192.168.102.107", port=8000)
