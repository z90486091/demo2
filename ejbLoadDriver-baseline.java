package com.poc.audit;

import jakarta.ejb.EJB;
import jakarta.ejb.Stateless;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import jakarta.ejb.TransactionAttribute;
import jakarta.ejb.TransactionAttributeType;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;

@Stateless
public class LoadDriver {

    @EJB private AuditServiceBaseline baseline;
    @EJB private AuditServiceSfusl sfusl;
    @EJB private AuditServiceLocal local;
    @EJB private ResultsTracker tracker;


    private final static Map<String, AtomicLong> lastUpdatedMap = new ConcurrentHashMap<>();

    /**
     * @param variant        "baseline" | "sfusl" | "local"
     * @param threads        number of concurrent callers
     * @param callsPerThread calls each thread makes
     * @param distinctUsers  number of distinct userIds — keep small relative to threads to force key overlap
     */
    @TransactionAttribute(TransactionAttributeType.NOT_SUPPORTED)
    public LoadResult runLoad(String variant, int threads, int callsPerThread, int distinctUsers) throws InterruptedException {
        lastUpdatedMap.clear();
        tracker.reset(variant);

        ExecutorService pool = Executors.newFixedThreadPool(threads*distinctUsers);
        CountDownLatch latch = new CountDownLatch(threads*distinctUsers);
        long start = System.currentTimeMillis();

        for (int u = 0; u < distinctUsers; u++) {
            String userId = "user_" + u;
            for (int t = 0; t < threads; t++) {
                // final String userId = "user" + (t % distinctUsers);
                pool.submit(() -> {
                    try {
                        for (int i = 0; i < callsPerThread; i++) {
                            try {

                                // debounce logic - BEGIN
                                long now = System.currentTimeMillis();
                                AtomicLong ts = lastUpdatedMap.computeIfAbsent(userId, k -> new AtomicLong(0));
                                long prev = ts.get();

                                System.out.println("now is: " +now);
                                System.out.println("prev is: " +prev);
                                if ((now-prev) < 5000) {
                                    //debounce hit
                                    System.out.println("Debouncing ...");
                                    return;
                                }
                                
                                // lastUpdatedMap.compareAndSet(userId, prev);
                                ts.compareAndSet(prev, now);
                                // debounce logic - END

                                switch (variant) {
                                    case "baseline": baseline.touch(userId, "sso-token"); System.out.println("userid is: " + userId); break;
                                    case "sfusl":    sfusl.touch(userId, "sso-token"); System.out.println("userid is: " + userId); break;
                                    case "local":    local.touch(userId, "sso-token"); System.out.println("userid is: " + userId); break;
                                }
                            } catch (Exception e) { 
                                System.err.println("Error during variant processing: " + e);
                                // throw e;
                            }
                        }
                    } finally {
                        latch.countDown();
                        try {
                            Thread.sleep(5001);                            
                        } catch (InterruptedException ie) {
                            System.err.println("Exception thrown: " +ie);
                        }
                    }
                });
            }
        }
        latch.await();
        pool.shutdown();
        long elapsedMs = System.currentTimeMillis() - start;

        long attempts = tracker.getAttempts(variant);
        long skips = tracker.getSkips(variant);
        long noSkips = tracker.getNoSkips(variant);
        return new LoadResult(variant, threads, callsPerThread, elapsedMs, attempts, skips, noSkips);
    }

    public static class LoadResult {
        public final String variant;
        public final int threads;
        public final int callsPerThread;
        public final long elapsedMs;
        public final long attempts;
        public final long skips;
        public final long noSkips;

        public LoadResult(String variant, int threads, int callsPerThread, long elapsedMs, long attempts, long skips, long noSkips) {
            this.variant = variant;
            this.threads = threads;
            this.callsPerThread = callsPerThread;
            this.elapsedMs = elapsedMs;
            this.attempts = attempts;
            this.skips = skips;
            this.noSkips = noSkips;
        }
    }
}
