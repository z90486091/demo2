import { ApplicationConfig, isDevMode } from '@angular/core';
import { provideHttpClient } from '@angular/common/http';
import { provideServiceWorker } from '@angular/service-worker';

export const appConfig: ApplicationConfig = {
  providers: [
    provideHttpClient(),
    provideServiceWorker('ngsw-worker.js', {
      enabled: !isDevMode(),
      // Check for a new SW as soon as the app stabilizes, then every 30 min.
      // Deliberately conservative for an MVP used to *watch* update behavior
      // during WSOD repro, not to hide it.
      registrationStrategy: 'registerWhenStable:30000',
    }),
  ],
};
