import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import type { FeaField, MeshPayload } from "../api";
import { stressRgb } from "../lib/colormap";
import { type DecodedMesh, decodeBytes, decodeMesh, faceOfTriangle } from "../lib/mesh";

export interface ViewportHandle {
  fit: () => void;
}

interface Props {
  mesh: MeshPayload | undefined;
  theme: "light" | "dark";
  selectedFeature: string | null;
  hoveredFeature: string | null;
  showEdges: boolean;
  /** FEA surface result; shown instead of the part while `showStress` is on. */
  stressField: FeaField | null;
  stressMax: number;
  showStress: boolean;
  onPickFeature: (feature: string | null) => void;
  onHoverFeature: (feature: string | null) => void;
}

interface Scene {
  renderer: THREE.WebGLRenderer;
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  controls: OrbitControls;
  grid: THREE.Group;
  part: THREE.Mesh | null;
  edges: THREE.LineSegments | null;
  decoded: DecodedMesh | null;
  stress: THREE.Mesh | null;
}

function cssColor(name: string): THREE.Color {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return new THREE.Color(value || "#888888");
}

function makeGrid(size: number): THREE.Group {
  const group = new THREE.Group();
  const step = size > 400 ? 50 : size > 120 ? 10 : 5;
  const divisions = Math.max(4, Math.round(size / step));
  const minor = new THREE.GridHelper(divisions * step, divisions, cssColor("--vp-grid-major"), cssColor("--vp-grid"));
  minor.rotation.x = Math.PI / 2; // CAD convention: Z is up, the grid is the XY plane
  group.add(minor);
  return group;
}

export const Viewport = forwardRef<ViewportHandle, Props>(function Viewport(props, ref) {
  const hostRef = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<Scene | null>(null);
  const propsRef = useRef(props);
  propsRef.current = props;

  // One-time scene setup.
  useEffect(() => {
    const host = hostRef.current!;
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    host.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 10000);
    camera.up.set(0, 0, 1);
    camera.position.set(150, -180, 130);
    scene.add(camera);
    scene.add(new THREE.HemisphereLight(0xffffff, 0x6b7a8c, 1.5));
    const key = new THREE.DirectionalLight(0xffffff, 1.6);
    key.position.set(1, 1.5, 2);
    camera.add(key); // light follows the view so the part always reads well

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.12;

    const grid = makeGrid(200);
    scene.add(grid);
    sceneRef.current = { renderer, scene, camera, controls, grid, part: null, edges: null, decoded: null, stress: null };

    const resize = () => {
      const { clientWidth: w, clientHeight: h } = host;
      if (!w || !h) return;
      renderer.setSize(w, h);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(host);
    resize();

    let frame = 0;
    const loop = () => {
      controls.update();
      renderer.render(scene, camera);
      frame = requestAnimationFrame(loop);
    };
    loop();

    // Picking: hover highlights a feature, click selects it.
    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    let downAt: [number, number] | null = null;
    const pick = (event: PointerEvent): string | null | undefined => {
      const s = sceneRef.current;
      if (!s?.part || !s.decoded || !s.part.visible) return undefined;
      const rect = renderer.domElement.getBoundingClientRect();
      pointer.set(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1);
      raycaster.setFromCamera(pointer, camera);
      const hit = raycaster.intersectObject(s.part, false)[0];
      if (!hit || hit.faceIndex == null) return null;
      return s.decoded.faces[faceOfTriangle(s.decoded, hit.faceIndex)]?.feature ?? null;
    };
    const onMove = (event: PointerEvent) => {
      if (event.buttons) return;
      const feature = pick(event);
      if (feature !== undefined && feature !== propsRef.current.hoveredFeature) propsRef.current.onHoverFeature(feature);
      renderer.domElement.style.cursor = feature ? "pointer" : "";
    };
    const onDown = (event: PointerEvent) => {
      downAt = [event.clientX, event.clientY];
    };
    const onUp = (event: PointerEvent) => {
      if (!downAt) return;
      const moved = Math.hypot(event.clientX - downAt[0], event.clientY - downAt[1]);
      downAt = null;
      if (moved > 4) return; // that was an orbit drag, not a click
      const feature = pick(event);
      if (feature !== undefined) propsRef.current.onPickFeature(feature);
    };
    const onLeave = () => propsRef.current.onHoverFeature(null);
    const el = renderer.domElement;
    el.addEventListener("pointermove", onMove);
    el.addEventListener("pointerdown", onDown);
    el.addEventListener("pointerup", onUp);
    el.addEventListener("pointerleave", onLeave);

    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      el.removeEventListener("pointermove", onMove);
      el.removeEventListener("pointerdown", onDown);
      el.removeEventListener("pointerup", onUp);
      el.removeEventListener("pointerleave", onLeave);
      controls.dispose();
      renderer.dispose();
      host.removeChild(el);
      sceneRef.current = null;
    };
  }, []);

  const fit = () => {
    const s = sceneRef.current;
    if (!s?.part) return;
    const box = new THREE.Box3().setFromObject(s.part);
    const sphere = box.getBoundingSphere(new THREE.Sphere());
    const distance = sphere.radius / Math.sin(THREE.MathUtils.degToRad(s.camera.fov / 2)) * 1.15;
    const direction = new THREE.Vector3(1, -1.25, 0.95).normalize();
    s.camera.position.copy(sphere.center).addScaledVector(direction, distance);
    s.camera.near = Math.max(0.1, distance / 100);
    s.camera.far = distance * 100;
    s.camera.updateProjectionMatrix();
    s.controls.target.copy(sphere.center);
    s.controls.update();
  };
  useImperativeHandle(ref, () => ({ fit }));

  // Swap in a new mesh when the build changes.
  useEffect(() => {
    const s = sceneRef.current;
    if (!s || !props.mesh) return;
    const previousRadius = s.part ? new THREE.Box3().setFromObject(s.part).getBoundingSphere(new THREE.Sphere()).radius : 0;
    for (const old of [s.part, s.edges]) {
      if (!old) continue;
      s.scene.remove(old);
      old.geometry.dispose();
      (old.material as THREE.Material).dispose();
    }
    const decoded = decodeMesh(props.mesh);
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(decoded.positions, 3));
    geometry.setAttribute("color", new THREE.BufferAttribute(new Float32Array(decoded.positions.length), 3));
    geometry.setIndex(new THREE.BufferAttribute(decoded.indices, 1));
    geometry.computeVertexNormals();
    const material = new THREE.MeshStandardMaterial({
      vertexColors: true,
      roughness: 0.55,
      metalness: 0.05,
      side: THREE.DoubleSide,
      polygonOffset: true,
      polygonOffsetFactor: 1,
      polygonOffsetUnits: 1,
    });
    s.part = new THREE.Mesh(geometry, material);
    s.decoded = decoded;
    s.scene.add(s.part);

    const edgeGeometry = new THREE.BufferGeometry();
    edgeGeometry.setAttribute("position", new THREE.BufferAttribute(decoded.edges, 3));
    s.edges = new THREE.LineSegments(edgeGeometry, new THREE.LineBasicMaterial({ color: cssColor("--vp-edge") }));
    s.edges.visible = props.showEdges;
    s.scene.add(s.edges);

    const box = new THREE.Box3().setFromObject(s.part);
    const size = box.getSize(new THREE.Vector3());
    s.scene.remove(s.grid);
    s.grid = makeGrid(Math.max(size.x, size.y) * 2.2);
    s.grid.position.set((box.min.x + box.max.x) / 2, (box.min.y + box.max.y) / 2, box.min.z);
    s.scene.add(s.grid);
    // Keep the user's camera unless the part changed size enough to leave the view.
    const radius = box.getBoundingSphere(new THREE.Sphere()).radius;
    if (!previousRadius || Math.abs(radius - previousRadius) / previousRadius > 0.2) fit();
    paint();
  }, [props.mesh]);

  // Recolor faces for selection and hover, and restyle on theme change.
  const paint = () => {
    const s = sceneRef.current;
    if (!s?.part || !s.decoded) return;
    const { selectedFeature, hoveredFeature } = propsRef.current;
    const base = cssColor("--vp-part");
    const select = cssColor("--vp-select");
    const hover = cssColor("--vp-hover");
    const colors = s.part.geometry.getAttribute("color") as THREE.BufferAttribute;
    s.decoded.faces.forEach((face, i) => {
      const color = face.feature && face.feature === selectedFeature ? select : face.feature && face.feature === hoveredFeature ? hover : base;
      const [lo, hi] = s.decoded!.faceVertices[i];
      for (let v = lo; v <= hi; v++) colors.setXYZ(v, color.r, color.g, color.b);
    });
    colors.needsUpdate = true;
    if (s.edges) {
      (s.edges.material as THREE.LineBasicMaterial).color = cssColor("--vp-edge");
      s.edges.visible = propsRef.current.showEdges;
    }
  };
  useEffect(paint, [props.selectedFeature, props.hoveredFeature, props.theme, props.showEdges]);

  // The stress heatmap: its own mesh (the FEA surface), coloured by von Mises stress.
  useEffect(() => {
    const s = sceneRef.current;
    if (!s) return;
    if (s.stress) {
      s.scene.remove(s.stress);
      s.stress.geometry.dispose();
      (s.stress.material as THREE.Material).dispose();
      s.stress = null;
    }
    const field = props.stressField;
    if (!field) return;
    const positions = new Float32Array(decodeBytes(field.positions));
    const indices = new Uint32Array(decodeBytes(field.indices));
    const values = new Float32Array(decodeBytes(field.von_mises));
    const colors = new Float32Array(positions.length);
    const max = props.stressMax > 0 ? props.stressMax : values.reduce((a, b) => Math.max(a, b), 0);
    values.forEach((v, i) => colors.set(stressRgb(v / max), i * 3));
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    geometry.setIndex(new THREE.BufferAttribute(indices, 1));
    geometry.computeVertexNormals();
    s.stress = new THREE.Mesh(
      geometry,
      new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.7, metalness: 0, side: THREE.DoubleSide }),
    );
    s.scene.add(s.stress);
    s.stress.visible = props.showStress;
  }, [props.stressField, props.stressMax]);

  useEffect(() => {
    const s = sceneRef.current;
    if (!s) return;
    const stress = props.showStress && s.stress !== null;
    if (s.stress) s.stress.visible = stress;
    if (s.part) s.part.visible = !stress;
    if (s.edges) s.edges.visible = !stress && props.showEdges;
  }, [props.showStress, props.stressField, props.showEdges, props.mesh]);

  useEffect(() => {
    const s = sceneRef.current;
    if (!s) return;
    const center = s.grid.position.clone();
    s.scene.remove(s.grid);
    const box = s.part ? new THREE.Box3().setFromObject(s.part) : null;
    const size = box ? box.getSize(new THREE.Vector3()) : new THREE.Vector3(100, 100, 0);
    s.grid = makeGrid(Math.max(size.x, size.y) * 2.2);
    s.grid.position.copy(center);
    s.scene.add(s.grid);
  }, [props.theme]);

  return <div className="viewport-canvas" ref={hostRef} />;
});
