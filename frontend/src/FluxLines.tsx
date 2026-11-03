import { useEffect, useRef } from 'react';
import './FluxLines.css';

type FluxLinesProps = {
  colors?: [string, string, string];
  glow?: number;
  rimWidth?: number;
  lineWidth?: number;
  flowDirection?: 'up' | 'down';
  mouseInteraction?: boolean;
  clickSwirl?: boolean;
  speed?: number;
  scale?: number;
  turbulence?: number;
  fluidity?: number;
  sharpness?: number;
  shimmer?: number;
  mouseStrength?: number;
  mouseRadius?: number;
  intro?: boolean;
  lightMode?: boolean;
};

const vertexShader = `
attribute vec2 a_position;
varying vec2 v_uv;

void main() {
  v_uv = a_position * 0.5 + 0.5;
  gl_Position = vec4(a_position, 0.0, 1.0);
}
`;

const fragmentShader = `
precision mediump float;

varying vec2 v_uv;
uniform vec2 u_resolution;
uniform float u_time;
uniform float u_speed;
uniform float u_scale;
uniform float u_turbulence;
uniform float u_fluidity;
uniform float u_sharpness;
uniform float u_shimmer;
uniform float u_glow;
uniform float u_rimWidth;
uniform float u_lineWidth;
uniform float u_flowDirection;
uniform float u_mouseStrength;
uniform float u_mouseRadius;
uniform float u_mouseActive;
uniform vec2 u_mouse;
uniform vec2 u_click;
uniform float u_clickAge;
uniform float u_intro;
uniform float u_lightMode;
uniform vec3 u_color;

float hash(vec2 p) {
  return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
}

float noise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  f = f * f * (3.0 - 2.0 * f);
  return mix(
    mix(hash(i), hash(i + vec2(1.0, 0.0)), f.x),
    mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), f.x),
    f.y
  );
}

void main() {
  float aspect = u_resolution.x / max(u_resolution.y, 1.0);
  vec2 p = v_uv - 0.5;
  p.x *= aspect;
  vec2 mouse = u_mouse - 0.5;
  mouse.x *= aspect;
  vec2 click = u_click - 0.5;
  click.x *= aspect;
  float time = u_time * u_speed;

  float mouseDistance = length(p - mouse);
  float mouseFalloff = exp(-mouseDistance * mouseDistance / max(u_mouseRadius * u_mouseRadius, 0.001));
  float clickDistance = length(p - click);
  float swirlLife = 1.0 - smoothstep(0.0, 2.4, u_clickAge);
  float swirl = exp(-clickDistance * clickDistance / 0.12) * swirlLife;

  float lineField = 0.0;
  float shimmerField = 0.0;
  for (int i = 0; i < 24; i++) {
    float index = float(i);
    float position = (index + 0.5) / 24.0;
    float baseX = (position - 0.5) * aspect * u_scale;
    float y = v_uv.y * u_scale;
    float wave = sin(y * 5.2 + time * 0.42 * u_flowDirection + index * 1.37) * 0.075;
    wave += sin(y * 10.7 + time * 0.25 * u_flowDirection + index * 0.79) * 0.026;
    wave += (noise(vec2(y * 2.1, index * 0.31 + time * 0.11)) - 0.5) * 0.08 * u_turbulence;
    wave += sin(y * 3.0 - time * 0.18 * u_flowDirection) * u_fluidity * 0.3;

    float mousePush = (mouse.x - p.x) * mouseFalloff * u_mouseStrength * u_mouseActive * 0.22;
    float swirlPush = sin(atan(p.y - click.y, p.x - click.x) * 2.0 + u_clickAge * 4.0)
      * swirl * 0.075;
    float distanceToLine = abs(p.x - baseX - wave - mousePush - swirlPush);
    float distanceInPixels = distanceToLine * u_resolution.y;
    float width = max(u_lineWidth, 0.25);
    float core = 1.0 - smoothstep(width * (1.0 - 0.4 / max(u_sharpness, 0.1)), width, distanceInPixels);
    float halo = exp(-distanceInPixels * 0.13) * u_glow * 0.02;
    float rim = exp(-abs(distanceInPixels - width * 1.6) * 0.6) * u_rimWidth * 0.05;
    float light = core * 0.38 + halo + rim;

    float verticalShimmer = 0.72 + 0.28 * sin(
      v_uv.y * 42.0 + time * 2.0 * u_flowDirection + index * 1.9
    ) * u_shimmer;
    float grain = 0.76 + noise(vec2(index * 3.2, y * 4.0 + time * 0.25 * u_flowDirection)) * 0.24;
    light *= verticalShimmer * grain;
    lineField = max(lineField, light);
    shimmerField = max(shimmerField, halo + rim);
  }

  float introFade = mix(1.0, smoothstep(0.0, 1.6, u_time), u_intro);
  float edgeFade = smoothstep(0.0, 0.12, v_uv.y) * (1.0 - smoothstep(0.88, 1.0, v_uv.y) * 0.16);
  float alpha = clamp((lineField + shimmerField * 0.12) * introFade * edgeFade, 0.0, 0.88);
  vec3 background = u_lightMode > 0.5 ? vec3(0.90, 0.92, 0.89) : vec3(0.035, 0.052, 0.055);
  vec3 color = mix(background, u_color, alpha);
  gl_FragColor = vec4(color, 1.0);
}
`;

function colorToRgb(color: string): [number, number, number] {
  const hex = color.replace('#', '');
  const normalized = hex.length === 3 ? hex.split('').map((value) => value + value).join('') : hex;
  const value = Number.parseInt(normalized, 16);
  return [(value >> 16 & 255) / 255, (value >> 8 & 255) / 255, (value & 255) / 255];
}

function createShader(gl: WebGLRenderingContext, type: number, source: string): WebGLShader | null {
  const shader = gl.createShader(type);
  if (!shader) return null;
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    console.error('FluxLines shader compilation failed:', gl.getShaderInfoLog(shader));
    gl.deleteShader(shader);
    return null;
  }
  return shader;
}

export default function FluxLines({
  colors = ['#ffffff', '#ffffff', '#ffffff'],
  glow = 2,
  rimWidth = 0.2,
  lineWidth = 1,
  flowDirection = 'down',
  mouseInteraction = true,
  clickSwirl = true,
  speed = 0.5,
  scale = 1.6,
  turbulence = 1,
  fluidity = 0.1,
  sharpness = 2.5,
  shimmer = 1.5,
  mouseStrength = 1,
  mouseRadius = 0.35,
  intro = true,
  lightMode = false,
}: FluxLinesProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const gl = canvas?.getContext('webgl', {
      alpha: false,
      antialias: false,
      depth: false,
      powerPreference: 'low-power',
      preserveDrawingBuffer: false,
    });
    if (!canvas || !gl) {
      console.error('FluxLines could not initialize WebGL; showing the static background instead.');
      return;
    }

    const vertex = createShader(gl, gl.VERTEX_SHADER, vertexShader);
    const fragment = createShader(gl, gl.FRAGMENT_SHADER, fragmentShader);
    if (!vertex || !fragment) {
      if (vertex) gl.deleteShader(vertex);
      if (fragment) gl.deleteShader(fragment);
      return;
    }

    const program = gl.createProgram();
    if (!program) {
      gl.deleteShader(vertex);
      gl.deleteShader(fragment);
      console.error('FluxLines could not create a WebGL program.');
      return;
    }
    gl.attachShader(program, vertex);
    gl.attachShader(program, fragment);
    gl.linkProgram(program);
    gl.deleteShader(vertex);
    gl.deleteShader(fragment);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      console.error('FluxLines program linking failed:', gl.getProgramInfoLog(program));
      gl.deleteProgram(program);
      return;
    }

    const buffer = gl.createBuffer();
    if (!buffer) {
      gl.deleteProgram(program);
      console.error('FluxLines could not allocate its WebGL buffer.');
      return;
    }
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]), gl.STATIC_DRAW);
    gl.useProgram(program);
    const position = gl.getAttribLocation(program, 'a_position');
    gl.enableVertexAttribArray(position);
    gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);

    const uniform = (name: string) => gl.getUniformLocation(program, name);
    const uniforms = {
      resolution: uniform('u_resolution'),
      time: uniform('u_time'),
      speed: uniform('u_speed'),
      scale: uniform('u_scale'),
      turbulence: uniform('u_turbulence'),
      fluidity: uniform('u_fluidity'),
      sharpness: uniform('u_sharpness'),
      shimmer: uniform('u_shimmer'),
      glow: uniform('u_glow'),
      rimWidth: uniform('u_rimWidth'),
      lineWidth: uniform('u_lineWidth'),
      flowDirection: uniform('u_flowDirection'),
      mouseStrength: uniform('u_mouseStrength'),
      mouseRadius: uniform('u_mouseRadius'),
      mouseActive: uniform('u_mouseActive'),
      mouse: uniform('u_mouse'),
      click: uniform('u_click'),
      clickAge: uniform('u_clickAge'),
      intro: uniform('u_intro'),
      lightMode: uniform('u_lightMode'),
      color: uniform('u_color'),
    };

    const rgb = colorToRgb(colors[0]);
    const pointer = { x: 0.5, y: 0.5, active: 0 };
    const click = { x: 0.5, y: 0.5, time: -10 };
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
    const startTime = performance.now();
    let frame = 0;
    let visible = !document.hidden;
    let intersectsViewport = true;

    const resize = () => {
      const ratio = Math.min(window.devicePixelRatio || 1, 1.25);
      const width = Math.max(1, Math.round(canvas.clientWidth * ratio));
      const height = Math.max(1, Math.round(canvas.clientHeight * ratio));
      if (canvas.width !== width || canvas.height !== height) {
        canvas.width = width;
        canvas.height = height;
      }
      gl.viewport(0, 0, width, height);
    };

    const render = (now: number) => {
      resize();
      const elapsed = reducedMotion.matches ? Math.max(1.6, (now - startTime) / 1000) : (now - startTime) / 1000;
      gl.useProgram(program);
      gl.uniform2f(uniforms.resolution, canvas.width, canvas.height);
      gl.uniform1f(uniforms.time, elapsed);
      gl.uniform1f(uniforms.speed, speed);
      gl.uniform1f(uniforms.scale, scale);
      gl.uniform1f(uniforms.turbulence, turbulence);
      gl.uniform1f(uniforms.fluidity, fluidity);
      gl.uniform1f(uniforms.sharpness, sharpness);
      gl.uniform1f(uniforms.shimmer, shimmer);
      gl.uniform1f(uniforms.glow, glow);
      gl.uniform1f(uniforms.rimWidth, rimWidth);
      gl.uniform1f(uniforms.lineWidth, lineWidth);
      gl.uniform1f(uniforms.flowDirection, flowDirection === 'down' ? 1 : -1);
      gl.uniform1f(uniforms.mouseStrength, mouseStrength);
      gl.uniform1f(uniforms.mouseRadius, mouseRadius);
      gl.uniform1f(uniforms.mouseActive, mouseInteraction ? pointer.active : 0);
      gl.uniform2f(uniforms.mouse, pointer.x, pointer.y);
      gl.uniform2f(uniforms.click, click.x, click.y);
      gl.uniform1f(uniforms.clickAge, elapsed - click.time);
      gl.uniform1f(uniforms.intro, intro ? 1 : 0);
      gl.uniform1f(uniforms.lightMode, lightMode ? 1 : 0);
      gl.uniform3f(uniforms.color, rgb[0], rgb[1], rgb[2]);
      gl.drawArrays(gl.TRIANGLES, 0, 6);
    };

    const animate = (now: number) => {
      frame = 0;
      if (!visible || !intersectsViewport) return;
      render(now);
      if (!reducedMotion.matches) frame = window.requestAnimationFrame(animate);
    };

    const schedule = () => {
      if (frame || !visible || !intersectsViewport) return;
      frame = window.requestAnimationFrame(animate);
    };
    const onPointerMove = (event: PointerEvent) => {
      pointer.x = event.clientX / window.innerWidth;
      pointer.y = 1 - event.clientY / window.innerHeight;
      pointer.active = 1;
    };
    const onPointerLeave = () => { pointer.active = 0; };
    const onClick = (event: MouseEvent) => {
      if (!clickSwirl) return;
      click.x = event.clientX / window.innerWidth;
      click.y = 1 - event.clientY / window.innerHeight;
      click.time = (performance.now() - startTime) / 1000;
    };
    const onVisibilityChange = () => {
      visible = !document.hidden;
      if (visible) schedule();
      else if (frame) {
        window.cancelAnimationFrame(frame);
        frame = 0;
      }
    };
    const onMotionChange = () => {
      if (frame) {
        window.cancelAnimationFrame(frame);
        frame = 0;
      }
      if (visible && intersectsViewport) schedule();
    };
    const observer = new IntersectionObserver(([entry]) => {
      intersectsViewport = entry.isIntersecting;
      if (intersectsViewport) schedule();
      else if (frame) {
        window.cancelAnimationFrame(frame);
        frame = 0;
      }
    });
    observer.observe(canvas);
    const resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(canvas);
    window.addEventListener('pointermove', onPointerMove, { passive: true });
    window.addEventListener('pointerleave', onPointerLeave, { passive: true });
    window.addEventListener('click', onClick, { passive: true });
    document.addEventListener('visibilitychange', onVisibilityChange);
    reducedMotion.addEventListener('change', onMotionChange);
    resize();
    schedule();

    return () => {
      if (frame) window.cancelAnimationFrame(frame);
      observer.disconnect();
      resizeObserver.disconnect();
      window.removeEventListener('pointermove', onPointerMove);
      window.removeEventListener('pointerleave', onPointerLeave);
      window.removeEventListener('click', onClick);
      document.removeEventListener('visibilitychange', onVisibilityChange);
      reducedMotion.removeEventListener('change', onMotionChange);
      gl.deleteBuffer(buffer);
      gl.deleteProgram(program);
    };
  }, [
    clickSwirl, colors, flowDirection, fluidity, glow, intro, lightMode, lineWidth,
    mouseInteraction, mouseRadius, mouseStrength, rimWidth, scale, sharpness, shimmer, speed, turbulence,
  ]);

  return <div className="flux-lines-container"><canvas ref={canvasRef} className="flux-lines-canvas" aria-hidden="true" /></div>;
}
