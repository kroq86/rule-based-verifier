(map!
 (:map 'override
  :v "v" #'er/expand-region
  :v "V" #'er/contract-region))

(defun open-term-on-right ()
  (interactive)
  (split-window-right)
  (other-window 1)
  (+vterm/here default-directory))

(map! :leader
      :desc "Open term on right"
      "p t" #'open-term-on-right)