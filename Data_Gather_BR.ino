#include <OneWire.h> //Temperatura
#include <DallasTemperature.h> //Temperatura
#include <MQUnifiedsensor.h> //Alcohol

//Temperatura
#define ONE_WIRE_BUS 15

OneWire oneWire(ONE_WIRE_BUS);
DallasTemperature sensors(&oneWire);

//pH
const int phPin = 32;

//Alcohol-Brix
#define         Board                   ("ESP-32") 
#define         Pin                     (34) 
/***********************Software Related Macros************************************/
#define         Type                    ("MQ-3") 
#define         Voltage_Resolution      (3.3)
#define         ADC_Bit_Resolution      (12) 
#define         RatioMQ2CleanAir        (60) 
/*****************************Globals***********************************************/
MQUnifiedsensor MQ2(Board, Voltage_Resolution, ADC_Bit_Resolution, Pin, Type);

//Presión
const int sensorPin = 33;
int lecturaADC = 0;
float voltaje = 0.0;
float presion = 0.0;  // En PSI

// Calibración
const float Vmin = 0.0;     // Voltaje con 0 PSI
const float Vmax = 3.3;     // Voltaje con presión máxima
const float Pmax = 150.0;   // Presión máxima del sensor (PSI)

void setup() {
  Serial.begin(115200);
  delay(1000);

  //Temperatura
  pinMode(ONE_WIRE_BUS, INPUT_PULLUP); // Activa la resistencia interna
  sensors.begin();

  //Alcohol-Brix
  MQ2.setRegressionMethod(1);
  MQ2.setA(0.3934); MQ2.setB(-1.504); 
  
  MQ2.init(); 
 
  Serial.print("Calibrating please wait.");
  float calcR0 = 0;
  for(int i = 1; i<=10; i ++)
  {
    MQ2.update();
    calcR0 += MQ2.calibrate(RatioMQ2CleanAir);
    Serial.print(".");
  }
  MQ2.setR0(calcR0/10);
  Serial.println("  done!.");
  
  if(isinf(calcR0)) {Serial.println("Warning: Conection issue, R0 is infinite (Open circuit detected) please check your wiring and supply"); while(1);}
  if(calcR0 == 0){Serial.println("Warning: Conection issue found, R0 is zero (Analog pin shorts to ground) please check your wiring and supply"); while(1);}
  
}

void loop() {
  //Temperatura
  sensors.requestTemperatures(); 
  float tempC = sensors.getTempCByIndex(0);
  delay(10);

  //pH
  int lectura = analogRead(phPin);
  float vpH = lectura * (3.3 / 4095.0);
  
  // Fórmula calibrada
  float pH = -8.82 * vpH + 33.106;
  delay(10);

  //Alcohol-Brix
  MQ2.update(); // Update data, the arduino will read the voltage from the analog pin
  float alcohol = MQ2.readSensor();
  float brix = -0.6801*(MQ2.readSensor())+14.195;
  delay(10);

  //Presion
  lecturaADC = analogRead(sensorPin);  // Rango 0–4095 (12 bits en ESP32)
  voltaje = lecturaADC * (3.3 / 4095.0);  // Conversión directa
  
  // Convertimos el voltaje a presión
  if (voltaje > Vmin) {
    presion = (voltaje - Vmin) / (Vmax - Vmin) * Pmax;
  } else {
    presion = 0;
  }
  delay(10);

  //Post
  Serial.print("{");

  Serial.printf("\"temperature\":%.2f,", tempC);
  Serial.printf("\"ph\":%.2f,", pH);

  if (isinf(alcohol) || isnan(alcohol)) Serial.print("\"alcohol\":null,");
  else Serial.printf("\"alcohol\":%.2f,", alcohol);

  if (isinf(brix) || isnan(brix)) Serial.print("\"brix\":null,");
  else Serial.printf("\"brix\":%.2f,", brix);

  Serial.printf("\"pressure\":%.2f", presion);

  Serial.println("}");

  delay(10000);
}
