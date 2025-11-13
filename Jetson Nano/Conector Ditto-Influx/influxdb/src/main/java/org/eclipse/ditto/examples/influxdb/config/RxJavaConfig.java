package org.eclipse.ditto.examples.influxdb.config;

import io.reactivex.plugins.RxJavaPlugins;
import io.reactivex.schedulers.Schedulers;
import org.springframework.context.annotation.Configuration;
import javax.annotation.PostConstruct;
import java.util.concurrent.Executors;

@Configuration
public class RxJavaConfig {

    @PostConstruct
    public void setupRxJavaConfig() {
        // Configurar RxJava para usar un scheduler limitado globalmente
        RxJavaPlugins.setComputationSchedulerHandler(s -> 
            Schedulers.from(Executors.newFixedThreadPool(10)));
        
        RxJavaPlugins.setIoSchedulerHandler(s -> 
            Schedulers.from(Executors.newFixedThreadPool(15)));
        
        RxJavaPlugins.setNewThreadSchedulerHandler(s -> 
            Schedulers.from(Executors.newFixedThreadPool(5)));
    }
}