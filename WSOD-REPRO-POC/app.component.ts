import { Component, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { SwUpdate, VersionEvent } from '@angular/service-worker';

interface ProbeResult {
  timestamp: string;
  path: string;
  status: number;
  contentLengthHeader: string | null;
  actualBodyBytes: number;
  suspectedWsod: boolean;
}

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <main style="font-family: system-ui, sans-serif; max-width: 720px; margin: 2rem auto;">
      <h1>WSOD Triage Harness</h1>

      <label>
        AFD endpoint base URL
        <input
          style="width: 100%; padding: 0.4rem;"
          [(ngModel)]="baseUrl"
          placeholder="https://wsod-endpoint-xxxx.z01.azurefd.net"
        />
      </label>

      <div style="margin-top: 1rem; display: flex; gap: 0.5rem;">
        <button (click)="probe('/good')">Call /good</button>
        <button (click)="probe('/zero')">Call /zero (expect 200, 0 bytes by design)</button>
        <button (click)="results.set([])">Clear log</button>
      </div>

      <p *ngIf="swStatus() as s" style="margin-top: 1rem;">
        <strong>Service worker:</strong> {{ s }}
      </p>

      <table style="width: 100%; margin-top: 1rem; border-collapse: collapse;">
        <thead>
          <tr>
            <th style="text-align:left; border-bottom: 1px solid #ccc;">Time</th>
            <th style="text-align:left; border-bottom: 1px solid #ccc;">Path</th>
            <th style="text-align:left; border-bottom: 1px solid #ccc;">Status</th>
            <th style="text-align:left; border-bottom: 1px solid #ccc;">Content-Length hdr</th>
            <th style="text-align:left; border-bottom: 1px solid #ccc;">Actual body bytes</th>
            <th style="text-align:left; border-bottom: 1px solid #ccc;">Flag</th>
          </tr>
        </thead>
        <tbody>
          <tr *ngFor="let r of results()">
            <td>{{ r.timestamp }}</td>
            <td>{{ r.path }}</td>
            <td>{{ r.status }}</td>
            <td>{{ r.contentLengthHeader }}</td>
            <td>{{ r.actualBodyBytes }}</td>
            <td [style.color]="r.suspectedWsod ? 'crimson' : 'inherit'">
              {{ r.suspectedWsod ? 'UNEXPECTED zero-byte 200' : 'ok' }}
            </td>
          </tr>
        </tbody>
      </table>
    </main>
  `,
})
export class AppComponent {
  baseUrl = '';
  results = signal<ProbeResult[]>([]);
  swStatus = signal<string>('');

  constructor(private http: HttpClient, private swUpdate: SwUpdate) {
    if (this.swUpdate.isEnabled) {
      this.swUpdate.versionUpdates.subscribe((evt: VersionEvent) => {
        this.swStatus.set(`${evt.type} @ ${new Date().toLocaleTimeString()}`);
        // Recommended Angular pattern: reload directly on VERSION_READY rather
        // than calling activateUpdate() first (avoids double-activation races).
        if (evt.type === 'VERSION_READY') {
          window.location.reload();
        }
      });
      this.swUpdate.unrecoverable.subscribe((evt) => {
        this.swStatus.set(`UNRECOVERABLE: ${evt.reason}`);
        window.location.reload();
      });
    } else {
      this.swStatus.set('disabled (dev mode or unsupported)');
    }
  }

  probe(path: '/good' | '/zero') {
    if (!this.baseUrl) {
      alert('Set the AFD endpoint base URL first.');
      return;
    }
    const url = `${this.baseUrl.replace(/\/$/, '')}${path}`;
    this.http.get(url, { observe: 'response', responseType: 'text' }).subscribe({
      next: (res) => this.recordResult(path, res.status, res.headers.get('content-length'), res.body?.length ?? 0),
      error: (err) => this.recordResult(path, err.status ?? 0, err.headers?.get?.('content-length') ?? null, err.error?.length ?? 0),
    });
  }

  private recordResult(path: string, status: number, contentLengthHeader: string | null, actualBodyBytes: number) {
    // /zero is EXPECTED to be a zero-byte 200 (that's the control case).
    // /good returning a zero-byte 200 is the WSOD signature we're hunting.
    const suspectedWsod = path === '/good' && status === 200 && actualBodyBytes === 0;
    this.results.update((r) => [
      { timestamp: new Date().toLocaleTimeString(), path, status, contentLengthHeader, actualBodyBytes, suspectedWsod },
      ...r,
    ]);
  }
}
