FROM admwscki/kicad-kbplacer-primary:8.0.9-jammy

RUN pip3 install --no-cache-dir hatch

COPY kbplacer/ /tmp/kbplacer

RUN mkdir -p ${HOME}/.local/share/kicad/8.0/3rdparty/plugins && \
    cp -r -n /tmp/kbplacer ${HOME}/.local/share/kicad/8.0/3rdparty/plugins/com_github_adamws_kicad-kbplacer
