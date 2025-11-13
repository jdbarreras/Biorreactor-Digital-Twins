/*
 * Copyright (c) 2019 Contributors to the Eclipse Foundation
 *
 * See the NOTICE file(s) distributed with this work for additional
 * information regarding copyright ownership.
 *
 * This program and the accompanying materials are made available under the
 * terms of the Eclipse Public License 2.0 which is available at
 * http://www.eclipse.org/legal/epl-2.0
 *
 * SPDX-License-Identifier: EPL-2.0
 */

package org.eclipse.ditto.examples.influxdb.service;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import javax.annotation.PreDestroy;
import org.eclipse.ditto.client.DittoClient;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.stereotype.Service;

@Service
public class DittoService {

  private static final Logger logger = LoggerFactory.getLogger(DittoService.class);

  @Autowired
  DittoClient client;

  @Autowired
  InfluxDBService influxDbService;

  // Executor con pool limitado
  private final ExecutorService processingExecutor = Executors.newFixedThreadPool(10);

  @EventListener(ApplicationReadyEvent.class)
  private void registerForChanges() throws InterruptedException, ExecutionException {

    client.twin().registerForFeaturesChanges("globalFeaturesHandler", change -> {
      // Procesar en el pool limitado en lugar de permitir hilos ilimitados
      processingExecutor.submit(() -> {
        try {
          logger.info("Received features update from device '{}': {}", change.getEntityId(),
              change.getFeatures().toJsonString());

          // BLOQUE try-finally para GARANTIZAR limpieza
          try {
            change.getFeatures().forEach(f -> {
              try {
                influxDbService.save(change.getEntityId().toString(), f.getId(),
                    f.getProperty("value").get().asDouble());
              } catch (Exception e) {
                logger.error("Error saving feature {} to InfluxDB", f.getId(), e);
              }
            });
          } finally {
            // GARBAGE COLLECTION periódico - cada ~10 segundos
            if (System.currentTimeMillis() % 10000 == 0) {
              System.gc();  // ← SUGIERE al JVM que haga garbage collection
            }
          }
        } catch (Exception e) {
          logger.error("Error processing feature change", e);
        }
      });
    });
  }

  @PreDestroy
  public void cleanup() {
    if (processingExecutor != null) {
      processingExecutor.shutdown();  // ← Deja de aceptar nuevos trabajos
      try {
        // Espera 5 segundos a que los trabajos actuales terminen
        if (!processingExecutor.awaitTermination(5, TimeUnit.SECONDS)) {
          processingExecutor.shutdownNow();  // ← Fuerza terminación si no termina en 5 seg
        }
      } catch (InterruptedException e) {
        processingExecutor.shutdownNow();  // ← Si hay interrupción, fuerza terminación
        Thread.currentThread().interrupt(); // ← Restaura flag de interrupción
      }
    }
  }
}