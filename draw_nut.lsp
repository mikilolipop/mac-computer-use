;; draw_nut.lsp - Automated 3D Hexagonal Nut Generator for AutoCAD 2026
(setvar "CMDECHO" 0)

;; 1. Draw outer hexagon (radius 20)
(command "_POLYGON" "6" "0,0" "_I" "20")
(setq poly (entlast))

;; 2. Extrude polygon to height 16
(command "_EXTRUDE" poly "" "16")
(setq hex_prism (entlast))

;; 3. Create inner through-hole cylinder (radius 10, height 20 from z=-2)
(command "_CYLINDER" "0,0,-2" "10" "20")
(setq hole_cyl (entlast))

;; 4. Boolean subtract hole from hexagonal prism
(command "_SUBTRACT" hex_prism "" hole_cyl "")

;; 5. Switch to Conceptual Visual Style and Isometric View
(command "_SHADEMODE" "_C")
(command "_VPOINT" "1,-1,1")
(command "_ZOOM" "_E")

(setvar "CMDECHO" 1)
(princ "\n[mac-cua] 3D Hexagonal Nut generated successfully!\n")
(princ)
