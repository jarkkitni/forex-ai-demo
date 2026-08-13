"use client";

import { useEffect, useRef } from "react";

/**
 * โหลด GSAP หลัง first paint เท่านั้น — ไม่ให้ถ่วง LCP
 * ครึ่งจอบนใช้ CSS ล้วน ไม่แตะ JS
 */
export function Reveal({ children }: { children: React.ReactNode }) {
  const host = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    let ctx: { revert: () => void } | undefined;
    let cancelled = false;

    (async () => {
      const [{ gsap }, { ScrollTrigger }] = await Promise.all([
        import("gsap"),
        import("gsap/ScrollTrigger"),
      ]);
      if (cancelled) return;
      gsap.registerPlugin(ScrollTrigger);

      // แตะแค่ transform/opacity — ไม่แตะ width/height/top ที่ทำให้ reflow ทุกเฟรม
      ctx = gsap.context(() => {
        gsap.to(".reveal", {
          opacity: 1,
          y: 0,
          duration: 0.7,
          ease: "power2.out",
          stagger: 0.06,
          scrollTrigger: { trigger: el, start: "top 82%", once: true },
        });
      }, el);
    })();

    return () => {
      cancelled = true;
      ctx?.revert();
    };
  }, []);

  return <div ref={host}>{children}</div>;
}
